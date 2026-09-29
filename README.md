# valny-showcase

> Independent samples on public data. They are not derived from, and do not describe, any employer system. Employer work is confidential.

Two small, self-contained projects built on public 10x PBMC3k single-cell data. Each has its own README, tests and CLI, and each runs offline in CI.

| Project | What it shows | Start here |
|---|---|---|
| [**healpipe**](healpipe/) | **An on-call agent pattern.** A runner executes jobs. A sentinel polls failed jobs, investigates with tools specific to each job type, then makes a gated, dry-runnable config write and relaunches, or escalates. It has an LLM planner (Claude) and a rules baseline. | [README](healpipe/README.md) · [walkthrough](healpipe/docs/WALKTHROUGH.md) |
| [**pipeboard**](pipeboard/) | **A small internal tool.** A form generated from a YAML schema, background jobs as subprocesses, live log streaming with cancel, and a self-contained HTML report. No agent. | [README](pipeboard/README.md) |

![pipeboard report UMAP](pipeboard/docs/screenshots/report-umap.png)

## Quick start

```bash
cd healpipe  && pip install -e ".[dev]" && pytest -q && python scripts/fetch_data.py && healpipe eval
cd pipeboard && pip install -e ".[dev]" && pytest -q && python scripts/fetch_data.py && pipeboard
```

CI (`.github/workflows/ci.yml`) runs both test suites on every push. It uses synthetic fixtures only, with no dataset download and no API keys.
