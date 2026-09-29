# valny-showcase

> Independent samples on public data. They are not derived from, and do not describe, any employer system. Employer work is confidential.

Three small, self-contained projects built on public single-cell and spatial data. Two are in Python and use 10x PBMC3k. The third is an R tutorial on a published mouse ovary spatial sample. Each has its own README and runs its checks offline in CI.

| Project | What it shows | Start here |
|---|---|---|
| [**healpipe**](healpipe/) | **An on-call agent pattern.** A runner executes jobs. A sentinel polls failed jobs, investigates with tools specific to each job type, then makes a gated, dry-runnable config write and relaunches, or escalates. It has an LLM planner (Claude) and a rules baseline. | [README](healpipe/README.md) · [walkthrough](healpipe/docs/WALKTHROUGH.md) |
| [**pipeboard**](pipeboard/) | **A small internal tool.** A form generated from a YAML schema, background jobs as subprocesses, live log streaming with cancel, and a self-contained HTML report. No agent. | [README](pipeboard/README.md) |
| [**ovary-spatial-tutorial**](ovary-spatial-tutorial/) | **An educational Seurat walkthrough** of one published mouse ovary Curio Seeker 3×3 sample (Mantri *et al.*, PNAS 2024; GEO GSE240271): QC → clustering → marker annotation → spatial maps → co-localization → Wilcoxon DE, with "Check your understanding" questions. R Markdown. | [README](ovary-spatial-tutorial/README.md) · [notebook](ovary-spatial-tutorial/ovary_analysis.Rmd) |

![pipeboard report UMAP](pipeboard/docs/screenshots/report-umap.png)

## Quick start

```bash
cd healpipe  && pip install -e ".[dev]" && pytest -q && python scripts/fetch_data.py && healpipe eval
cd pipeboard && pip install -e ".[dev]" && pytest -q && python scripts/fetch_data.py && pipeboard
cd ovary-spatial-tutorial && pip install -r scripts/requirements.txt && python scripts/fetch_data.py \
  && Rscript -e 'rmarkdown::render("ovary_analysis.Rmd")'   # optional and heavy; reading the notebook is enough
```

CI (`.github/workflows/ci.yml`) runs on every push:
- **healpipe** and **pipeboard**: the Python test suites, on synthetic fixtures only, with no dataset download and no API keys.
- **ovary-spatial-tutorial**: the repo hygiene checks, and a check that every R chunk parses.

## Data and credit

- **PBMC3k:** 10x Genomics, via the example dataset in CZI's cellxgene repository.
- **Mouse ovary:** Mantri M, Zhang HH, Spanos E, Ren YA, De Vlaminck I., *Proc Natl Acad Sci USA* 121(5):e2317418121 (2024). The tutorial is not affiliated with the paper's authors or their institutions beyond citing their work.

No data files are committed. Each project has a fetch script.
