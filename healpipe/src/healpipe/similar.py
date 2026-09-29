"""lookup_similar_traces: search this demo's own past investigation traces by symptom."""

from __future__ import annotations

import json
import re
from pathlib import Path

_TOKEN = re.compile(r"[a-z][a-z0-9_\-]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def search(traces_dir: Path | None, symptom: str, limit: int = 3, exclude_job: str | None = None) -> list[dict]:
    """Rank past traces by overlap with `symptom`, with a bonus when the failed check name matches."""
    if traces_dir is None or not Path(traces_dir).exists():
        return []
    query = _tokens(symptom)
    hits = []
    for path in sorted(Path(traces_dir).glob("*.trace.json")):
        try:
            t = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        s = t.get("summary") or {}
        if not s.get("symptom") or t.get("job_id") == exclude_job:
            continue
        past = _tokens(s["symptom"])
        score = len(query & past) / max(len(query | past), 1)
        if s.get("check") and s["check"] in symptom:
            score += 1.0
        if score > 0.2:
            hits.append(
                {
                    "score": round(score, 2),
                    "job_type": t.get("job_type"),
                    "symptom": s["symptom"],
                    "outcome": s.get("outcome"),
                    "config_changes": s.get("changes", []),
                    "escalation_reason": s.get("escalation_reason"),
                }
            )
    return sorted(hits, key=lambda h: -h["score"])[:limit]
