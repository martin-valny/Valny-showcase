import json

from healpipe.planners import Outcome, finish


def test_second_poll_investigates_nothing(make):
    env = make()
    ids = [env.runner.submit(n, env.clean) for n in ("species_mislabel", "negative_values")]
    first = env.sentinel.poll()
    assert set(first.handled) == set(ids)
    second = env.sentinel.poll()
    assert second.handled == {}
    assert set(env.sentinel.processed) == set(ids)


def test_processed_ids_are_skipped_even_if_cursor_is_lost(make):
    env = make()
    job_id = env.runner.submit("negative_values", env.clean)
    env.sentinel.poll()
    (env.sentinel.state_dir / "cursor.json").unlink()  # e.g. state partially wiped

    again = env.sentinel.poll()
    assert again.handled == {} and again.skipped == [job_id]
    assert json.loads((env.sentinel.state_dir / "processed.json").read_text()) == [job_id]


class RelaunchThenEscalate:
    """Applies a (wrong) fix, relaunches, sees it still fail, escalates. The job's rev moves past the cursor."""

    name = "scripted"

    def investigate(self, inv):
        inv.call("set_job_config", {"rationale": "x", "key": "input_scale", "value": "log1p", "dry_run": False})
        inv.call("request_relaunch", {"rationale": "x"})
        inv.call("escalate", {"rationale": "x", "reason": "still failing", "evidence": ""})
        return finish(inv)


def test_job_relaunched_during_investigation_is_not_reinvestigated(make):
    env = make(planner=RelaunchThenEscalate())
    job_id = env.runner.submit("negative_values", env.clean)
    env.sentinel.poll()
    assert env.api.get_job(job_id)["status"] == "failed"
    second = env.sentinel.poll()
    assert second.skipped == [job_id] and second.handled == {}


def test_non_terminal_outcome_is_not_recorded(make):
    env = make(shadow=True)
    env.runner.submit("species_mislabel", env.clean)
    env.sentinel.poll()
    assert env.sentinel.processed == []
    assert isinstance(Outcome("proposed"), Outcome)
