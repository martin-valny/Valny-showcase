"""Structured investigation log: symptom -> hypothesis -> action -> outcome."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Trace:
    job_id: str
    scenario: str
    job_type: str
    planner: str
    events: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)  # symptom / outcome / changes, for lookup_similar_traces
    _t0: float = field(default_factory=time.monotonic)

    def add(self, kind: str, **data) -> None:
        self.events.append({"t": round(time.monotonic() - self._t0, 2), "kind": kind, **data})

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "scenario": self.scenario,
            "job_type": self.job_type,
            "planner": self.planner,
            "summary": self.summary,
            "events": self.events,
        }

    def write(self, out_dir: Path) -> tuple[Path, Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{self.scenario}.{self.planner}"
        j, m = out_dir / f"{stem}.trace.json", out_dir / f"{stem}.trace.md"
        j.write_text(json.dumps(self.to_dict(), indent=2, default=str))
        m.write_text(self.to_markdown())
        return j, m

    def to_markdown(self) -> str:
        lines = [f"# Investigation: `{self.job_id}` ({self.job_type}, scenario `{self.scenario}`, planner: {self.planner})", ""]
        for e in self.events:
            k = e["kind"]
            if k == "job_failed":
                lines.append(f"**[{e['t']:>6}s] sentinel** picked up failed `{self.job_type}` job `{self.job_id}` (rev {e['rev']})")
                for c in e.get("failed_checks", []):
                    lines.append(f"  - symptom: `{c['step']}.{c['name']}`: {c['message']}")
            elif k == "job_run":
                lines.append(f"**[{e['t']:>6}s] runner** relaunched from `{e['from_step']}` -> **{e['status'].upper()}**")
                for c in e.get("failed_checks", []):
                    lines.append(f"  - symptom: `{c['step']}.{c['name']}`: {c['message']}")
            elif k == "tool_call":
                args = {a: v for a, v in e["input"].items() if a != "rationale"}
                lines.append(f"**[{e['t']:>6}s] agent** -> `{e['tool']}({json.dumps(args)[1:-1]})`")
                if e["input"].get("rationale"):
                    lines.append(f"  - hypothesis: {e['input']['rationale']}")
            elif k == "tool_result":
                lines.append(f"  - result: {json.dumps(e['result'], default=str)[:400]}")
            elif k == "notify":
                lines.append(f"**[{e['t']:>6}s] notify**: {e['message']}")
            elif k == "outcome":
                lines += [f"**Outcome: {e['outcome'].upper()}**: {e.get('detail', '')}"]
            elif k == "note":
                lines.append(f"_{e['text']}_")
            lines.append("")
        return "\n".join(lines)
