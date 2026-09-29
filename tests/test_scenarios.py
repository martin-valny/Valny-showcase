import pytest

from healpipe.evaluation import run_scenarios
from healpipe.faults import SCENARIOS
from healpipe.pipeline import Pipeline
from healpipe.faults import materialize

ORIGINAL_SIX = ["clean", "prenormalized_input", "transposed_matrix", "species_mislabel", "shallow_sequencing", "negative_values"]


def test_original_six_still_scored_correctly(make):
    env = make()
    rows, _, _ = run_scenarios(env, ORIGINAL_SIX, env.clean)
    assert [(r.scenario, r.correct) for r in rows] == [(n, True) for n in ORIGINAL_SIX], [r.note for r in rows]


def test_stacked_fault_needs_two_writes_and_one_relaunch(make):
    env = make()
    rows, _, _ = run_scenarios(env, ["transposed_prenormalized"], env.clean)
    (row,) = rows
    assert row.correct and row.outcome.outcome == "fixed"
    assert {c["key"] for c in row.outcome.applied} == {"orientation", "input_scale"}
    assert env.api.get_job(row.job_id)["attempts"] == 1


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_every_fault_actually_breaks_the_run(name, clean_h5ad, tmp_path):
    s = SCENARIOS[name]
    result = Pipeline(materialize(s, clean_h5ad, tmp_path), s.config).run()
    assert (result.status == "passed") == (s.expected == "clean")


def test_recovered_jobs_match_clean_annotation(make):
    env = make()
    rows, _, _ = run_scenarios(env, ["clean", "transposed_matrix", "species_mislabel"], env.clean)
    clean, *fixed = rows
    assert clean.agreement > 0.9
    assert all(r.agreement == pytest.approx(clean.agreement) for r in fixed)
