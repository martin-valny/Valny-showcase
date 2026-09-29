import pytest

from healpipe.api import Rejected
from healpipe.evaluation import run_scenarios


def test_dry_run_validates_but_writes_nothing(make):
    env = make()
    job_id = env.runner.submit("species_mislabel", env.clean)
    jobs_file = env.store.path
    before = jobs_file.read_bytes()

    out = env.api.set_job_config(job_id, {"species": "human"}, dry_run=True)

    assert out["status"] == "would_apply" and out["patch"] == {"species": "human"}
    assert jobs_file.read_bytes() == before  # byte-identical: no rev bump, no config change
    job = env.api.get_job(job_id)
    assert job["config"]["species"] == "mouse" and job["attempts"] == 0 and job["pending_from"] is None


def test_apply_writes_and_marks_relaunch_step(make):
    env = make()
    job_id = env.runner.submit("species_mislabel", env.clean)
    out = env.api.set_job_config(job_id, {"species": "human"})
    assert out["status"] == "applied" and out["relaunch_from"] == "qc"
    assert env.api.get_job(job_id)["config"]["species"] == "human"


@pytest.mark.parametrize("patch", [{"input_scale": "log1p"}, {"species": "martian"}, {"species": "mouse"}, {"min_genes": 1}])
def test_same_validation_in_both_modes(make, patch):
    env = make()
    job_id = env.runner.submit("species_mislabel", env.clean)
    errors = []
    for dry in (True, False):
        with pytest.raises(Rejected) as e:
            env.api.set_job_config(job_id, patch, dry_run=dry)
        errors.append(str(e.value))
    assert errors[0] == errors[1]


def test_shadow_mode_sentinel_proposes_and_changes_nothing(make):
    env = make(shadow=True)
    rows, first, _ = run_scenarios(env, ["species_mislabel"], env.clean)
    (row,) = rows
    assert row.outcome.outcome == "proposed"
    assert row.outcome.proposed == [{"key": "species", "new": "human"}] and not row.outcome.applied
    job = env.api.get_job(row.job_id)
    assert job["status"] == "failed" and job["config"]["species"] == "mouse" and job["attempts"] == 0
    assert row.job_id not in env.sentinel.processed  # not terminal: a live sentinel will pick it up
