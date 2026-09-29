from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from conftest import REPO
from pipeboard.jobs import JobError, load_schema, validate_params
from pipeboard.server import create_app


def test_every_parameter_has_name_type_default_within_bounds():
    schema = load_schema(REPO / "schema" / "pipeline.yaml")
    assert schema["parameters"]
    for p in schema["parameters"]:
        assert {"name", "type", "default"} <= set(p)
        assert p.get("min", p["default"]) <= p["default"] <= p.get("max", p["default"])


def test_api_schema_returns_parameters(project):
    body = TestClient(create_app(project)).get("/api/schema").json()
    expected = yaml.safe_load((REPO / "schema" / "pipeline.yaml").read_text())
    assert body == expected
    assert [p["name"] for p in body["parameters"]] == ["min_genes", "max_mito_pct", "n_hvgs", "n_neighbors"]


def test_editing_yaml_changes_the_form_spec_without_code_changes(project):
    path = project / "schema" / "pipeline.yaml"
    schema = yaml.safe_load(path.read_text())
    schema["parameters"].append({"name": "demo_flag", "type": "bool", "default": True, "help": "added in YAML only"})
    path.write_text(yaml.safe_dump(schema))
    names = [p["name"] for p in TestClient(create_app(project)).get("/api/schema").json()["parameters"]]
    assert names[-1] == "demo_flag"


def test_frontend_has_no_hardcoded_parameter_names():
    js = (REPO / "src" / "pipeboard" / "static" / "app.js").read_text()
    html = (REPO / "src" / "pipeboard" / "static" / "index.html").read_text()
    for p in load_schema(REPO / "schema" / "pipeline.yaml")["parameters"]:
        assert p["name"] not in js and p["name"] not in html


def test_validation_fills_defaults_and_rejects_bad_values():
    schema = load_schema(REPO / "schema" / "pipeline.yaml")
    assert validate_params(schema, {})["min_genes"] == 200
    assert validate_params(schema, {"min_genes": "300"})["min_genes"] == 300
    for bad in ({"min_genes": -1}, {"min_genes": 2.5}, {"n_neighbors": 999}, {"nope": 1}, {"max_mito_pct": "x"}):
        with pytest.raises(JobError) as e:
            validate_params(schema, bad)
        assert e.value.status == 422


def test_schema_missing_default_is_rejected(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("parameters:\n  - name: x\n    type: int\n")
    with pytest.raises(ValueError, match="default"):
        load_schema(p)
