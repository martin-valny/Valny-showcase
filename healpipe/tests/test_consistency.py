from healpipe.evaluation import grade, run_scenarios
from healpipe.planners import Outcome, finish


class FixThenEscalate:
    """Applies the right fix, relaunches (job succeeds), and escalates anyway."""

    name = "scripted"

    def investigate(self, inv):
        inv.call("set_job_config", {"rationale": "x", "key": "species", "value": "human", "dry_run": False})
        inv.call("request_relaunch", {"rationale": "x"})
        inv.escalation = {"reason": "not sure", "evidence": ""}  # bypasses `done` on purpose
        return finish(inv)


def test_write_then_escalate_is_graded_incorrect(make):
    env = make(planner=FixThenEscalate())
    (row,), _, _ = run_scenarios(env, ["species_mislabel"], env.clean)
    assert row.outcome.outcome == "escalated"
    assert not row.correct and row.note.startswith("inconsistent")


def test_escalate_without_writes_is_fine_for_escalation_scenarios():
    ok, _ = grade("negative_values", Outcome("escalated"), {"config": {}})
    assert ok
