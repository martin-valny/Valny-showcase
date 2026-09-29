"""Record a Claude investigation once, replay it anywhere without an API key.

Recording (one JSON file per scenario):
    healpipe eval --planner claude --record docs/claude_recordings

Replay (no key, no network):
    healpipe eval --planner replay

The replay does not print a transcript. It feeds Claude's recorded tool calls
back through the *real* runner, JobAPI, toolkits and guardrails. So a reviewer
sees the same investigation run end to end, and the scorecard is graded exactly
as for a live run.

Each recorded call also keeps what Claude saw back: the result and whether it
was an error. If the live result disagrees on replay (a call that succeeded
now fails, or a relaunch now ends in a different status), the replay stops and
escalates, and the trace says where it diverged. That's how a stale recording
shows up after the code changes.

Only text and tool_use blocks are stored. Thinking blocks are not needed to
replay, and are left out.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .planners import Outcome, finish, gated_call
from .toolkits import Investigation

FORMAT = 1
DEFAULT_DIR = Path("docs/claude_recordings")


@dataclass
class Recording:
    scenario: str
    job_type: str
    model: str
    effort: str
    recorded_at: str
    turns: list[dict] = field(default_factory=list)
    outcome: str | None = None
    _inv: Investigation | None = field(default=None, repr=False)

    @classmethod
    def start(cls, inv: Investigation, model: str, effort: str) -> "Recording":
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return cls(inv.trace.scenario, inv.job_type, model, effort, now, _inv=inv)

    def add_turn(self, response) -> dict:
        turn = {
            "stop_reason": response.stop_reason,
            "text": [b.text for b in response.content if b.type == "text" and b.text.strip()],
            "tool_uses": [{"id": b.id, "name": b.name, "input": dict(b.input)} for b in response.content if b.type == "tool_use"],
            "results": [],  # filled in by the planner as each tool runs
        }
        self.turns.append(turn)
        return turn

    def to_dict(self) -> dict:
        if self._inv is not None:
            outcomes = [e["outcome"] for e in self._inv.trace.events if e["kind"] == "outcome"]
            self.outcome = outcomes[-1] if outcomes else None
        return {
            "format": FORMAT,
            "scenario": self.scenario,
            "job_type": self.job_type,
            "model": self.model,
            "effort": self.effort,
            "recorded_at": self.recorded_at,
            "outcome": self.outcome,
            "turns": self.turns,
        }

    def save(self, directory: Path | str) -> Path:
        path = Path(directory) / f"{self.scenario}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=str) + "\n")
        return path


def load(directory: Path | str, scenario: str) -> dict | None:
    path = Path(directory) / f"{scenario}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if data.get("format") != FORMAT:
        raise ValueError(f"{path}: unsupported recording format {data.get('format')!r}")
    return data


def _diverged(recorded: dict, live: dict) -> str | None:
    if recorded["is_error"] != ("error" in live):
        was = "an error" if recorded["is_error"] else "ok"
        now = f"error: {live.get('error')}" if "error" in live else "ok"
        return f"recorded result was {was}, live result is {now}"
    r, l = recorded.get("result") or {}, live
    if "status" in r and "status" in l and r["status"] != l["status"]:
        return f"recorded status {r['status']!r}, live status {l['status']!r}"
    return None


class ReplayPlanner:
    """Re-runs recorded Claude decisions through the live tools. No API key needed."""

    name = "replay"

    def __init__(self, recordings_dir: Path | str = DEFAULT_DIR):
        self.dir = Path(recordings_dir)

    def investigate(self, inv: Investigation) -> Outcome:
        rec = load(self.dir, inv.trace.scenario)
        if rec is None:
            return finish(inv, f"no Claude recording for scenario {inv.trace.scenario!r} in {self.dir}")
        if rec["job_type"] != inv.job_type:
            return finish(inv, f"recording is for a {rec['job_type']!r} job, this job is {inv.job_type!r}")
        inv.trace.add("note", text=f"replaying Claude recording: {rec['model']}, effort={rec['effort']}, recorded {rec['recorded_at']}")

        for turn in rec["turns"]:
            if turn["stop_reason"] in ("refusal", "max_tokens"):
                return finish(inv, f"planner stopped: {turn['stop_reason']} (recorded)")
            for text in turn["text"]:
                inv.trace.add("note", text=f"claude: {text}")
            if not turn["tool_uses"]:
                break
            for tu, recorded in zip(turn["tool_uses"], turn["results"]):
                live = gated_call(inv, tu["name"], tu["input"])
                why = _diverged(recorded, live)
                if why:
                    # Stop, even if the job happens to be fixed: this is no longer Claude's recorded run.
                    inv.trace.add("note", text=f"replay diverged at {tu['name']}: {why}")
                    inv.escalation = {"reason": f"replay diverged from the recording at {tu['name']} ({why}); re-record", "evidence": why}
                    return finish(inv)
        return finish(inv, "recording ended without resolving the job")
