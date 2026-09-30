"""Planners decide which tools to call for one failed job.

Both planners share one tool surface (`toolkits.Investigation`) and one trace format:

* ClaudePlanner: the LLM plans. It sees only the shared tools plus the job type's kit.
* RulePlanner: a hand-written triage table. It is a deterministic baseline and
  lets tests and the eval run offline with no API key.
* ReplayPlanner (replay.py): re-runs a recorded Claude investigation through the
  real tools and guardrails, so reviewers can see Claude's decisions with no key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .toolkits import Investigation, tool_specs

SYSTEM_PROMPT = """\
You are the on-call sentinel for a batch runner that executes single-cell RNA-seq jobs. \
The runner has reported a failed job of type `{job_type}`. You cannot see or change \
the pipeline code. You can read the job record and its input artifact, patch the \
job's config (only the keys this job type owns), ask the runner to relaunch, notify, \
or escalate.

How to work:
- Start from the failed checks in the job record. Gather evidence with the read-only \
tools before writing anything. State your hypothesis in each call's `rationale`.
- lookup_similar_traces can suggest a fix. Confirm it with evidence before acting on it.
- QC thresholds belong to the analysis owner and cannot be patched. If the job would \
only "pass" with looser thresholds, the data is the problem: escalate.
- Corrupted values (negative counts, NaNs) and data that is too shallow or low-quality \
are not config problems: escalate with the numbers that show it.
- Fix every cause the evidence supports (one set_job_config per key, dry_run=false), \
then request one relaunch. If the relaunch reveals a new failure, diagnose that one the same way.
- Do not escalate after a patch you applied has fixed the job. If you escalate, do it \
before writing, or explain which applied patch was wrong.
- When the job succeeds, notify once with a one-line summary. Then, or after escalating, \
stop calling tools and reply with two sentences.
"""


# After the job has succeeded (or been escalated), only these calls still make sense.
# The prompt asks Claude to notify once on success, so that must stay possible.
AFTER_RESOLUTION = {"notify", "inspect_job"}


def gated_call(inv: Investigation, name: str, args: dict) -> dict:
    """inv.call, except writes/relaunches/escalations are refused once the job is resolved."""
    if inv.done and name not in AFTER_RESOLUTION:
        return {"error": "job is already resolved; only notify is still allowed"}
    return inv.call(name, args)


@dataclass
class Outcome:
    outcome: str  # "fixed" | "escalated" | "proposed"
    applied: list[dict] = field(default_factory=list)
    proposed: list[dict] = field(default_factory=list)
    tool_calls: int = 0
    detail: str = ""


def finish(inv: Investigation, fallback_reason: str = "planner ended without resolving the job") -> Outcome:
    if not inv.done and not (inv.shadow and inv.proposed):
        inv.call("escalate", {"rationale": "unresolved", "reason": fallback_reason, "evidence": ""})
    n_calls = sum(e["kind"] == "tool_call" for e in inv.trace.events)
    if inv.escalation:
        o = Outcome("escalated", inv.applied, inv.proposed, n_calls, inv.escalation["reason"])
    elif inv.api.get_job(inv.job_id)["status"] == "succeeded":
        o = Outcome("fixed", inv.applied, inv.proposed, n_calls, f"applied: {inv.applied}")
    else:
        o = Outcome("proposed", inv.applied, inv.proposed, n_calls, f"shadow mode, would apply: {inv.proposed}")
    inv.trace.add("outcome", outcome=o.outcome, detail=o.detail)
    return o


# ------------------------------------------------------------------ Claude


class ClaudePlanner:
    name = "claude"

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "medium", max_turns: int = 14, record_dir=None):
        import anthropic

        self.client = anthropic.Anthropic()
        # the SDK only fails on the first request; fail here instead so the CLI can say what's missing
        if not any(getattr(self.client, a, None) for a in ("api_key", "auth_token", "credentials")):
            raise TypeError("no API key, auth token or credentials found")
        self.model, self.effort, self.max_turns = model, effort, max_turns
        self.record_dir = record_dir  # if set, save each investigation as a replayable recording

    def investigate(self, inv: Investigation) -> Outcome:
        from .replay import Recording

        rec = Recording.start(inv, self.model, self.effort)
        try:
            return self._investigate(inv, rec)
        finally:
            if self.record_dir:
                rec.save(self.record_dir)

    def _investigate(self, inv: Investigation, rec) -> Outcome:
        job = inv.api.get_job(inv.job_id)
        brief = {"job_error" if k == "error" else k: job[k] for k in ("id", "job_type", "status", "error", "failed_checks", "attempts_left")}
        messages = [{"role": "user", "content": "Failed job:\n" + json.dumps(brief, indent=2) + "\nInvestigate and recover."}]
        tools = [{**t, "strict": True} for t in tool_specs(inv.job_type)]
        system = SYSTEM_PROMPT.format(job_type=inv.job_type)

        for _ in range(self.max_turns):
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system,
                tools=tools,
                messages=messages,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                # If the primary model declines, the API re-runs the request
                # server-side on a fallback model, routed by category.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            turn = rec.add_turn(response)
            if response.stop_reason in ("refusal", "max_tokens"):
                return finish(inv, f"planner stopped: {response.stop_reason}")

            # Append content unchanged (thinking blocks included) to keep history append-only.
            messages.append({"role": "assistant", "content": response.content})
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                text = " ".join(b.text for b in response.content if b.type == "text").strip()
                if text:
                    inv.trace.add("note", text=f"agent summary: {text}")
                break

            results = []
            for tu in tool_uses:
                out = gated_call(inv, tu.name, dict(tu.input))
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(out, default=str), "is_error": "error" in out})
                turn["results"].append({"tool_use_id": tu.id, "is_error": "error" in out, "result": out})
            messages.append({"role": "user", "content": results})
        return finish(inv, f"no resolution within {self.max_turns} turns")


# ------------------------------------------------------------------ rules


class RulePlanner:
    """Hand-written triage. It encodes the same playbook the LLM is told to follow."""

    name = "rules"

    def investigate(self, inv: Investigation) -> Outcome:
        for _ in range(4):
            if inv.done:
                break
            job = inv.call("inspect_job", {"rationale": "start from the failed checks"})
            fixes: list[tuple[str, str]] = []
            for check in job["failed_checks"]:
                fix = self._diagnose(inv, check)
                if inv.escalation:
                    return finish(inv)
                if fix and fix not in fixes:
                    fixes.append(fix)
            if not fixes:
                break
            for key, value in fixes:
                inv.call("set_job_config", {"rationale": f"evidence points at {key}", "key": key, "value": value, "dry_run": False})
            if inv.shadow:
                break
            r = inv.call("request_relaunch", {"rationale": f"verify the fix for {[k for k, _ in fixes]}"})
            if "error" in r:
                break
        if inv.done and not inv.escalation:
            inv.call("notify", {"rationale": "close the loop", "message": f"{inv.job_id} recovered via {inv.applied}"})
        return finish(inv)

    def _diagnose(self, inv: Investigation, check: dict):
        """Return (key, value) for a fix, None if the check needs no change, or escalate."""
        key = f"{check['step']}.{check['name']}"

        def esc(reason: str, evidence: dict) -> None:
            inv.call("escalate", {"rationale": reason, "reason": reason, "evidence": json.dumps(evidence)})

        def need(tool: str, rationale: str) -> dict | None:
            r = inv.call(tool, {"rationale": rationale})
            if "error" in r:
                esc(f"cannot investigate {key} with the {inv.job_type} toolkit", r)
                return None
            return r

        if key == "load.finite_nonnegative":
            m = need("inspect_matrix", "check how widespread the invalid values are")
            if m:
                esc("matrix contains invalid values; upstream correction is broken", {k: m[k] for k in ("n_nan", "n_negative")})
            return None

        if key == "load.orientation":
            m = need("inspect_matrix", "observations are not barcodes; maybe the matrix is transposed")
            if m is None:
                return None
            if m["var_barcode_like_fraction"] > 0.5 > m["obs_barcode_like_fraction"]:
                return ("orientation", "genes_x_cells")
            return esc("cannot identify the cell axis", m)

        if key == "load.value_scale":
            m = need("inspect_matrix", "non-integer values: normalized input or corruption?")
            if m is None:
                return None
            if m["n_negative"] == 0 and (m["max"] or 0) < 20 and m.get("expm1_per_cell_total_cv", 1) < 0.05:
                return ("input_scale", "log1p")
            return esc("non-integer values that do not look like log-normalized data", m)

        if key in ("qc.mito_genes_detected", "annotate.marker_overlap"):
            g = need("inspect_gene_names", "maybe the gene nomenclature does not match the configured species")
            if g is None:
                return None
            inferred = "human" if g["fraction_all_uppercase"] > 0.8 and g["n_prefixed_MT-"] > 0 else (
                "mouse" if g["fraction_titlecase"] > 0.6 and g["n_prefixed_mt-"] > 0 else None
            )
            species = inv.api.get_job(inv.job_id)["config"]["species"]
            if inferred and inferred != species:
                return ("species", inferred)
            return esc("gene naming does not explain the failure", g)

        if key == "qc.cells_retained":
            q = need("inspect_qc_distribution", "most cells fail QC: bad config or bad library?")
            if q:
                esc("library too shallow: most cells are below the QC floor, and thresholds are not agent-editable", q)
            return None

        return esc(f"no playbook entry for {key}", check)
