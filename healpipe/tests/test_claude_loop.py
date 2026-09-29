"""Exercise ClaudePlanner's tool loop against a scripted stand-in for the API (dummy key, no network)."""

from types import SimpleNamespace as NS

import pytest

from healpipe.evaluation import run_scenarios
from healpipe.planners import ClaudePlanner
from healpipe.toolkits import KITS


def _tool_use(i, name, **inp):
    return NS(type="tool_use", id=f"tu_{i}", name=name, input={"rationale": "test", **inp})


class ScriptedClient:
    def __init__(self, turns):
        self.turns, self.requests = list(turns), []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})  # snapshot: the planner keeps appending
        content = self.turns.pop(0)
        stop = "tool_use" if any(b.type == "tool_use" for b in content) else "end_turn"
        return NS(content=content, stop_reason=stop)


@pytest.fixture
def planner(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-dummy-key")

    def _make(turns):
        p = ClaudePlanner()
        p.client = ScriptedClient(turns)
        return p

    return _make


def test_annotate_job_fixed_and_sees_only_annotate_tools(make, planner):
    p = planner(
        [
            [_tool_use(1, "inspect_gene_names")],
            [_tool_use(2, "set_job_config", key="species", value="human", dry_run=False)],
            [_tool_use(3, "request_relaunch")],
            [_tool_use(4, "notify", message="recovered")],
            [NS(type="text", text="Species was mislabeled; patched and relaunched.")],
        ]
    )
    env = make(planner=p)
    (row,), _, _ = run_scenarios(env, ["species_mislabel"], env.clean)
    assert row.correct and row.outcome.outcome == "fixed"

    first = p.client.requests[0]
    names = {t["name"] for t in first["tools"]}
    assert not names & set(KITS["ingest"]) and set(KITS["annotate"]) <= names
    assert all(t["strict"] for t in first["tools"])
    assert "`annotate`" in first["system"]
    # tool results answer the preceding tool_use ids
    assert p.client.requests[-1]["messages"][-1]["content"][0]["tool_use_id"] == "tu_4"


def test_rejected_write_is_reported_as_tool_error(make, planner):
    p = planner(
        [
            [_tool_use(1, "set_job_config", key="species", value="human", dry_run=False)],
            [_tool_use(2, "escalate", reason="library too shallow", evidence="median 73 genes/cell")],
            [NS(type="text", text="Escalated.")],
        ]
    )
    env = make(planner=p)
    (row,), _, _ = run_scenarios(env, ["shallow_sequencing"], env.clean)
    result = p.client.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] and "already 'human'" in result["content"]
    assert row.outcome.outcome == "escalated" and row.correct


def test_successful_calls_are_not_flagged_as_errors(make, planner):
    """Regression: job records carry their own error text; a successful tool call must not look like a failure to Claude."""
    p = planner(
        [
            [_tool_use(1, "inspect_job")],
            [_tool_use(2, "set_job_config", key="species", value="human", dry_run=False)],
            [_tool_use(3, "request_relaunch")],
            [NS(type="text", text="done")],
        ]
    )
    env = make(planner=p)
    run_scenarios(env, ["species_mislabel"], env.clean)
    results = [m["content"][0] for m in p.client.requests[-1]["messages"] if m["role"] == "user" and isinstance(m["content"], list)]
    assert [r["is_error"] for r in results] == [False, False, False]
    assert "qc.mito_genes_detected" in results[0]["content"]  # the job's failure is still visible, as job_error
