"""`healpipe run/eval` download the dataset on first use if it is missing (faked here, no network)."""

import shutil

from healpipe import cli


def test_missing_data_is_fetched_then_used(clean_h5ad, tmp_path, monkeypatch, capsys):
    data = tmp_path / "data" / "pbmc3k_counts.h5ad"
    fetched = []

    def fake_fetch(path):
        fetched.append(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(clean_h5ad, path)
        return path

    monkeypatch.setattr("healpipe.data.fetch", fake_fetch)
    rc = cli.main(["--state", str(tmp_path / "state"), "--runs", str(tmp_path / "runs"),
                   "run", "--scenario", "clean", "--data", str(data)])
    assert rc == 0 and fetched == [data]
    assert "downloading public PBMC3k" in capsys.readouterr().out


def test_no_fetch_reports_missing_data(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("healpipe.data.fetch", lambda path: (_ for _ in ()).throw(AssertionError("must not fetch")))
    rc = cli.main(["run", "--scenario", "clean", "--no-fetch", "--data", str(tmp_path / "nope.h5ad")])
    assert rc == 2 and "scripts/fetch_data.py" in capsys.readouterr().err
