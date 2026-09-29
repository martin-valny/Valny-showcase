"""Record a (scripted) Claude investigation, then replay it offline through the real tools."""

import json
from types import SimpleNamespace as NS

import pytest

from healpipe.evaluation import run_scenarios
from healpipe.replay import ReplayPlanner
from test_claude_loop import ScriptedClient, _tool_use

SPECIES_TURNS = [
    [NS(type="text", text="QC found no mt- genes; checking nomenclature."), _tool_use(1, "inspect_gene_names")],
    [_tool_use(2, "set_job_config", key="species", value="human", dry_run=False)],
    [_tool_use(3, "request_relaunch")],
    [_tool_use(4, "notify", message="recovered: species=human")],
    [NS(type="text", text="Species was mislabeled; patched and relaunched.")],
]


@pytest.fixture
def recorded(make, monkeypatch, tmp_path):
    """Run ClaudePlanner (scripted client) with recording on; return the recordings dir."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-dummy-key")
    from healpipe.planners import ClaudePlanner

    rec_dir = tmp_path / "recordings"
    p = ClaudePlanner(record_dir=rec_dir)
    p.client = ScriptedClient(SPECIES_TURNS)
    env = make(planner=p)
    (row,), _, _ = run_scenarios(env, ["species_mislabel"], env.clean)
    assert row.outcome.outcome == "fixed"
    return rec_dir


def _tool_calls(trace):
    return [(e["tool"], {k: v for k, v in e["input"].items() if k != "rationale"}) for e in trace.events if e["kind"] == "tool_call"]


def test_recording_has_turns_results_and_outcome(recorded):
    rec = json.loads((recorded / "species_mislabel.json").read_text())
    assert rec["format"] == 1 and rec["job_type"] == "annotate" and rec["outcome"] == "fixed"
    assert [t["tool_uses"][0]["name"] for t in rec["turns"] if t["tool_uses"]] == [
        "inspect_gene_names", "set_job_config", "request_relaunch", "notify"
    ]
    relaunch = rec["turns"][2]["results"][0]
    assert relaunch["is_error"] is False and relaunch["result"]["status"] == "succeeded"
    assert "thinking" not in json.dumps(rec)


def test_replay_reproduces_the_investigation_without_a_key(recorded, make, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    env = make(planner=ReplayPlanner(recorded))
    (row,), _, _ = run_scenarios(env, ["species_mislabel"], env.clean)
    assert row.correct and row.outcome.outcome == "fixed"
    assert env.api.get_job(row.job_id)["config"]["species"] == "human"

    trace = env.sentinel.traces[row.job_id]
    assert [t for t, _ in _tool_calls(trace)] == ["inspect_gene_names", "set_job_config", "request_relaunch", "notify"]
    notes = [e["text"] for e in trace.events if e["kind"] == "note"]
    assert any(n.startswith("replaying Claude recording") for n in notes)
    assert any("checking nomenclature" in n for n in notes)  # Claude's own words are kept


def test_replay_stops_and_escalates_when_live_results_diverge(recorded, make):
    path = recorded / "species_mislabel.json"
    rec = json.loads(path.read_text())
    rec["turns"][2]["results"][0]["result"]["status"] = "failed"  # pretend the recorded relaunch had failed
    path.write_text(json.dumps(rec))

    env = make(planner=ReplayPlanner(recorded))
    (row,), _, _ = run_scenarios(env, ["species_mislabel"], env.clean)
    assert row.outcome.outcome == "escalated"
    assert "diverged" in row.outcome.detail and "request_relaunch" in row.outcome.detail


def test_missing_recording_escalates_with_a_clear_reason(tmp_path, make):
    env = make(planner=ReplayPlanner(tmp_path / "empty"))
    (row,), _, _ = run_scenarios(env, ["negative_values"], env.clean)
    assert row.outcome.outcome == "escalated" and "no Claude recording" in row.outcome.detail


def test_recording_for_wrong_job_type_is_rejected(recorded, make):
    (recorded / "species_mislabel.json").rename(recorded / "transposed_matrix.json")
    env = make(planner=ReplayPlanner(recorded))
    (row,), _, _ = run_scenarios(env, ["transposed_matrix"], env.clean)
    assert row.outcome.outcome == "escalated" and "'annotate' job" in row.outcome.detail
