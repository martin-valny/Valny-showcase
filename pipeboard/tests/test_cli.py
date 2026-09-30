"""`pipeboard` downloads the dataset on first start if it is missing (no network or server in tests)."""

import sys
import types

import pytest

from pipeboard import __main__ as cli


@pytest.fixture
def fake_env(monkeypatch):
    calls = {"fetch": [], "serve": []}
    monkeypatch.setattr("pipeboard.data.fetch", lambda path: calls["fetch"].append(path))
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda app, **kw: calls["serve"].append(kw)))
    return calls


def test_missing_data_is_fetched_before_serving(project, fake_env):
    (project / "data" / "pbmc3k_counts.h5ad").unlink()
    assert cli.main(["--root", str(project)]) == 0
    assert fake_env["fetch"] == [project / "data" / "pbmc3k_counts.h5ad"]
    assert fake_env["serve"] and fake_env["serve"][0]["host"] == "127.0.0.1"


def test_existing_data_is_not_refetched(project, fake_env):
    cli.main(["--root", str(project)])
    assert fake_env["fetch"] == [] and fake_env["serve"]


def test_no_fetch_flag_skips_download(project, fake_env):
    (project / "data" / "pbmc3k_counts.h5ad").unlink()
    cli.main(["--root", str(project), "--no-fetch"])
    assert fake_env["fetch"] == [] and fake_env["serve"]


def test_failed_download_still_starts_the_ui(project, monkeypatch, capsys):
    (project / "data" / "pbmc3k_counts.h5ad").unlink()

    def boom(path):
        raise OSError("offline")

    served = []
    monkeypatch.setattr("pipeboard.data.fetch", boom)
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda app, **kw: served.append(kw)))
    cli.main(["--root", str(project)])
    assert served and "download failed" in capsys.readouterr().err
