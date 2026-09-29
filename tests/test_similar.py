from healpipe.evaluation import run_scenarios
from healpipe.toolkits import Investigation
from healpipe.trace import Trace


def test_lookup_finds_past_fix_for_same_symptom(make):
    env = make()
    run_scenarios(env, ["species_mislabel", "negative_values"], env.clean)  # leaves traces behind

    job_id = env.runner.submit("species_mislabel", env.clean)
    job = env.api.get_job(job_id)
    inv = Investigation(job_id, env.api, Trace(job_id, "species_mislabel", "annotate", "test"), traces_dir=env.sentinel.traces_dir)
    matches = inv.call("lookup_similar_traces", {"rationale": "x", "symptom": job["error"]})["matches"]

    assert matches and matches[0]["outcome"] == "fixed"
    assert matches[0]["config_changes"] == [{"key": "species", "new": "human"}]
    assert all("negative" not in m["symptom"] for m in matches[:1])


def test_lookup_with_no_history_is_empty(make):
    env = make()
    job_id = env.runner.submit("negative_values", env.clean)
    inv = Investigation(job_id, env.api, Trace(job_id, "negative_values", "ingest", "test"), traces_dir=env.sentinel.traces_dir)
    assert inv.call("lookup_similar_traces", {"rationale": "x", "symptom": "anything"}) == {"matches": []}
