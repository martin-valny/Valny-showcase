"""Each job type's investigation sees only its own kit and can only write its own keys."""

from healpipe.config import JOB_TYPE_KEYS
from healpipe.toolkits import KITS, SHARED_TOOLS, Investigation, tool_names, tool_specs
from healpipe.trace import Trace


def _inv(env, scenario):
    job_id = env.runner.submit(scenario, env.clean)
    return Investigation(job_id, env.api, Trace(job_id, scenario, env.api.get_job(job_id)["job_type"], "test"))


def test_tool_lists_are_isolated():
    ingest, annotate = set(tool_names("ingest")), set(tool_names("annotate"))
    assert not ingest & set(KITS["annotate"])
    assert not annotate & set(KITS["ingest"])
    assert set(SHARED_TOOLS) <= ingest & annotate


def test_specs_restrict_writable_keys_per_type():
    for job_type, keys in JOB_TYPE_KEYS.items():
        spec = next(t for t in tool_specs(job_type) if t["name"] == "set_job_config")
        assert spec["input_schema"]["properties"]["key"]["enum"] == list(keys)
        assert {t["name"] for t in tool_specs(job_type)} == set(tool_names(job_type))


def test_annotate_job_cannot_call_ingest_tool_or_write_ingest_key(make):
    env = make()
    inv = _inv(env, "species_mislabel")
    assert inv.job_type == "annotate"
    assert "not available for 'annotate'" in inv.call("inspect_matrix", {"rationale": "x"})["error"]
    out = inv.call("set_job_config", {"rationale": "x", "key": "input_scale", "value": "log1p", "dry_run": False})
    assert "not editable for job type 'annotate'" in out["error"]
    assert env.api.get_job(inv.job_id)["config"]["input_scale"] == "counts"


def test_ingest_job_cannot_call_annotate_tool_or_write_species(make):
    env = make()
    inv = _inv(env, "transposed_matrix")
    assert "not available for 'ingest'" in inv.call("inspect_gene_names", {"rationale": "x"})["error"]
    out = inv.call("set_job_config", {"rationale": "x", "key": "species", "value": "mouse", "dry_run": False})
    assert "owned by job type 'annotate'" in out["error"]


def test_thresholds_not_editable_by_any_type(make):
    env = make()
    job_id = env.runner.submit("shallow_sequencing", env.clean)
    for patch in ({"min_genes": 10}, {"max_pct_mito": 50.0}):
        try:
            env.api.set_job_config(job_id, patch)
        except Exception as e:
            assert "threshold" in str(e)
        else:
            raise AssertionError("threshold patch accepted")
    assert env.api.get_job(job_id)["config"]["min_genes"] == 200
