"""The sentinel's tools: a shared kit plus one kit per job type. Every tool is deterministic Python.

The LLM picks the tool and its arguments, and the tools do the work.
Guardrails are enforced in code:

* an investigation only sees, and can only call, the shared tools plus its job type's kit
* writes go through `JobAPI.set_job_config`, which only accepts keys the job type owns
  (QC thresholds are owned by nobody), and every write can be dry-run
* relaunches go through the runner: they need a pending config change and are budget-capped
* inspection tools are read-only and look at the job's input artifact, not pipeline internals
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import anndata as ad
import numpy as np
import scipy.sparse as sp

from . import similar
from .api import JobAPI, Rejected
from .config import AGENT_EDITABLE, JOB_TYPE_KEYS
from .markers import MITO_PREFIX
from .monitor import barcode_fraction
from .trace import Trace

SHARED_TOOLS = ["inspect_job", "lookup_similar_traces", "set_job_config", "request_relaunch", "notify", "escalate"]
KITS: dict[str, list[str]] = {
    "ingest": ["inspect_matrix"],
    "annotate": ["inspect_gene_names", "inspect_qc_distribution"],
}


class ToolError(Exception):
    pass


def tool_names(job_type: str) -> list[str]:
    return SHARED_TOOLS[:1] + KITS[job_type] + SHARED_TOOLS[1:]


def _load_oriented(job: dict) -> ad.AnnData:
    a = ad.read_h5ad(job["input_uri"])
    return a.T.copy() if job["config"]["orientation"] == "genes_x_cells" else a


@dataclass
class Investigation:
    job_id: str
    api: JobAPI
    trace: Trace
    traces_dir: Path | None = None
    shadow: bool = False  # dry-run every write, never relaunch
    job_type: str = ""
    applied: list[dict] = field(default_factory=list)
    proposed: list[dict] = field(default_factory=list)
    escalation: dict | None = None

    def __post_init__(self):
        self.job_type = self.api.get_job(self.job_id)["job_type"]

    # ------------------------------------------------------------ dispatch

    def call(self, name: str, args: dict) -> dict:
        self.trace.add("tool_call", tool=name, input=args)
        try:
            if name not in tool_names(self.job_type):
                raise ToolError(f"tool '{name}' is not available for {self.job_type!r} jobs; available: {tool_names(self.job_type)}")
            params = {k: v for k, v in args.items() if k != "rationale"}
            result, ok = getattr(self, f"tool_{name}")(**params), True
        except (ToolError, Rejected, TypeError, ValueError) as e:
            result, ok = {"error": str(e)}, False
        self.trace.add("tool_result", tool=name, ok=ok, result=result)
        return result

    @property
    def done(self) -> bool:
        return self.escalation is not None or self.api.get_job(self.job_id)["status"] == "succeeded"

    # ------------------------------------------------------------ shared: read-only

    def tool_inspect_job(self) -> dict:
        j = self.api.get_job(self.job_id)
        return {
            "id": j["id"],
            "job_type": j["job_type"],
            "status": j["status"],
            "error": j["error"],
            "failed_checks": j["failed_checks"],
            "config": j["config"],
            "editable_keys": {k: sorted(AGENT_EDITABLE[k][0]) for k in JOB_TYPE_KEYS[j["job_type"]]},
            "attempts_left": j["attempts_left"],
            "recent_events": j["events"][-5:],
        }

    def tool_lookup_similar_traces(self, symptom: str) -> dict:
        return {"matches": similar.search(self.traces_dir, symptom, exclude_job=self.job_id)}

    # ------------------------------------------------------------ ingest kit

    def tool_inspect_matrix(self) -> dict:
        """Facts about the input file exactly as stored on disk, before any orientation fix."""
        a = ad.read_h5ad(self.api.get_job(self.job_id)["input_uri"])
        X = (a.X if sp.issparse(a.X) else sp.csr_matrix(a.X)).tocsr()
        v = X.data
        finite = v[np.isfinite(v)]
        out = {
            "shape_on_disk": list(a.shape),
            "obs_name_examples": list(map(str, a.obs_names[:4])),
            "var_name_examples": list(map(str, a.var_names[:4])),
            "obs_barcode_like_fraction": round(barcode_fraction(a.obs_names), 3),
            "var_barcode_like_fraction": round(barcode_fraction(a.var_names), 3),
            "density": round(X.nnz / (X.shape[0] * X.shape[1]), 4),
            "n_nan": int(np.isnan(v).sum()),
            "n_negative": int((v < 0).sum()),
            "min_nonzero": float(finite.min()) if finite.size else None,
            "max": float(finite.max()) if finite.size else None,
            "frac_nonzero_integer": round(float(np.mean(finite == np.round(finite))), 4) if finite.size else None,
        }
        # If values look log-scaled: after expm1, are per-cell totals ~constant?
        # A constant total means cells were library-size normalized before the log.
        cell_axis = 1 if out["var_barcode_like_fraction"] > out["obs_barcode_like_fraction"] else 0
        if finite.size and out["frac_nonzero_integer"] < 0.999 and out["n_negative"] == 0:
            E = X.copy()
            E.data = np.expm1(E.data)
            sums = np.asarray(E.sum(axis=1 - cell_axis)).ravel()
            sums = sums[sums > 0]
            out["expm1_per_cell_total_median"] = round(float(np.median(sums)), 1)
            out["expm1_per_cell_total_cv"] = round(float(sums.std() / sums.mean()), 4)
        return out

    # ------------------------------------------------------------ annotate kit

    def tool_inspect_gene_names(self) -> dict:
        """Gene nomenclature on the gene axis, respecting the job's orientation config."""
        job = self.api.get_job(self.job_id)
        a = ad.read_h5ad(job["input_uri"], backed="r")
        genes = a.obs_names if job["config"]["orientation"] == "genes_x_cells" else a.var_names
        genes = [str(g) for g in genes]
        letters = [g for g in genes if any(c.isalpha() for c in g)]
        upper = sum(g == g.upper() for g in letters) / max(len(letters), 1)
        title = sum(g[:1].isupper() and g[1:] == g[1:].lower() for g in letters) / max(len(letters), 1)
        return {
            "n_genes": len(genes),
            "examples": genes[:3] + [g for g in genes if g.upper().startswith("MT-")][:3],
            "fraction_all_uppercase": round(upper, 3),
            "fraction_titlecase": round(title, 3),
            "n_prefixed_MT-": sum(g.startswith(MITO_PREFIX["human"]) for g in genes),
            "n_prefixed_mt-": sum(g.startswith(MITO_PREFIX["mouse"]) for g in genes),
            "note": "Human symbols are conventionally uppercase (MT-CO1). Mouse symbols are title-case (mt-Co1).",
        }

    def tool_inspect_qc_distribution(self) -> dict:
        """Per-cell depth and complexity of the input, compared with the job's (fixed) QC thresholds."""
        job = self.api.get_job(self.job_id)
        a = _load_oriented(job)
        X = (a.X if sp.issparse(a.X) else sp.csr_matrix(a.X)).tocsr()
        counts = X.copy()
        if job["config"]["input_scale"] == "log1p":
            counts.data = np.expm1(counts.data)
        n_genes = np.asarray((X > 0).sum(axis=1)).ravel()
        total = np.asarray(counts.sum(axis=1)).ravel()
        q = lambda x: {p: round(float(np.percentile(x, p)), 1) for p in (5, 25, 50, 75, 95)}
        min_genes = job["config"]["min_genes"]
        return {
            "n_cells": int(a.n_obs),
            "genes_per_cell_percentiles": q(n_genes),
            "umis_per_cell_percentiles": q(total),
            "min_genes_threshold": min_genes,
            "fraction_cells_passing_min_genes": round(float((n_genes >= min_genes).mean()), 3),
            "note": "QC thresholds are fixed by the analysis owner and are not agent-editable.",
        }

    # ------------------------------------------------------------ shared: actions

    def tool_set_job_config(self, key: str, value: str, dry_run: bool = False) -> dict:
        forced = self.shadow and not dry_run
        result = self.api.set_job_config(self.job_id, {key: value}, dry_run=dry_run or self.shadow)
        if result["status"] == "applied":
            self.applied.append({"key": key, "new": value})
        else:
            self.proposed.append({"key": key, "new": value})
        if forced:
            result["note"] = "shadow mode: write converted to dry-run"
        return result

    def tool_request_relaunch(self) -> dict:
        if self.shadow:
            raise ToolError("shadow mode: relaunch disabled; the proposed patch has been recorded")
        result = self.api.request_relaunch(self.job_id)
        self.trace.add("job_run", from_step=result["from_step"], status=result["status"], failed_checks=result["failed_checks"])
        return result

    def tool_notify(self, message: str) -> dict:
        print(f"[notify] {self.job_id}: {message}")
        self.trace.add("notify", message=message)
        return {"sent": True}

    def tool_escalate(self, reason: str, evidence: str = "") -> dict:
        self.escalation = {"reason": reason, "evidence": evidence}
        return {"escalated": True, "message": "A human has been paged. Stop here."}


# ------------------------------------------------------------------ schemas


def _prop(desc: str, enum: list[str] | None = None) -> dict:
    p = {"type": "string", "description": desc}
    if enum:
        p["enum"] = enum
    return p


def _schema(props: dict | None = None) -> dict:
    props = {"rationale": _prop("One sentence: the hypothesis this call tests, or why you are taking this action."), **(props or {})}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_DESCRIPTIONS = {
    "inspect_job": "The job record: status, error, failed checks, config, the keys this job type may edit, relaunch budget, and recent events.",
    "lookup_similar_traces": "Search past investigations in this deployment by symptom text. Returns how similar failures ended and which config changes fixed them. Treat it as a hint and verify with inspect tools.",
    "inspect_matrix": "Read-only facts about the input matrix as stored on disk: shape, axis name examples, barcode-likeness of each axis, value range, integer fraction, negatives/NaNs, and for log-looking data whether per-cell expm1 totals are constant (a sign it was normalized before the log).",
    "inspect_gene_names": "Read-only gene nomenclature summary: case conventions and counts of human-style (MT-) versus mouse-style (mt-) mitochondrial genes.",
    "inspect_qc_distribution": "Read-only per-cell depth and complexity distributions, compared with the job's fixed QC thresholds.",
    "set_job_config": "Patch one config key this job type owns. With dry_run=true it only validates and returns would_apply, and nothing changes. Thresholds are never editable.",
    "request_relaunch": "Ask the runner to relaunch this job after a config patch. The runner resumes from the earliest step the patch affects. Budget-limited.",
    "notify": "Post a short status message for the on-call channel (stdout in this demo).",
    "escalate": "Stop and hand off to a human. Use it when the evidence points at the data itself, when the fix needs a non-editable setting, or when you are not confident.",
}


def tool_specs(job_type: str) -> list[dict]:
    keys = list(JOB_TYPE_KEYS[job_type])
    values = sorted({v for k in keys for v in AGENT_EDITABLE[k][0]})
    extra = {
        "lookup_similar_traces": {"symptom": _prop("Symptom text, e.g. the job's error line.")},
        "set_job_config": {
            "key": _prop("Config key owned by this job type.", keys),
            "value": _prop("New value.", values),
            "dry_run": {"type": "boolean", "description": "true = validate only, change nothing."},
        },
        "notify": {"message": _prop("Message text.")},
        "escalate": {"reason": _prop("Short diagnosis for the human."), "evidence": _prop("Key numbers that support it.")},
    }
    return [{"name": n, "description": _DESCRIPTIONS[n], "input_schema": _schema(extra.get(n))} for n in tool_names(job_type)]
