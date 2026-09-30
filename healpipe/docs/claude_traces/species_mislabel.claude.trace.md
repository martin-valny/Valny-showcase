# Investigation: `job-0005` (annotate, scenario `species_mislabel`, planner: claude)

**[   0.0s] sentinel** picked up failed `annotate` job `job-0005` (rev 15)
  - symptom: `qc.mito_genes_detected`: 0 mitochondrial genes matched prefix 'mt-'

**[  15.7s] agent** -> `inspect_job()`
  - hypothesis: Check config species and editable keys; hypothesis: species set to mouse but data is human.

  - result: {"id": "job-0005", "job_type": "annotate", "status": "failed", "job_error": "qc.mito_genes_detected: 0 mitochondrial genes matched prefix 'mt-'", "failed_checks": [{"step": "qc", "name": "mito_genes_detected", "ok": false, "message": "0 mitochondrial genes matched prefix 'mt-'", "metrics": {"prefix": "mt-", "n_mito_genes": 0}}], "config": {"species": "mouse", "input_scale": "counts", "orientation"

**[  15.7s] agent** -> `inspect_gene_names()`
  - hypothesis: Test whether genes use human-style MT- prefix instead of mouse mt-.

  - result: {"n_genes": 13714, "examples": ["AL627309.1", "AP006222.2", "RP11-206L10.2", "MT-ND1", "MT-ND2", "MT-CO1"], "fraction_all_uppercase": 0.976, "fraction_titlecase": 0.023, "n_prefixed_MT-": 13, "n_prefixed_mt-": 0, "note": "Human symbols are conventionally uppercase (MT-CO1). Mouse symbols are title-case (mt-Co1)."}

**[ 15.74s] agent** -> `inspect_qc_distribution()`
  - hypothesis: Check that depth/complexity pass thresholds so the data itself is not the problem.

  - result: {"n_cells": 2638, "genes_per_cell_percentiles": {"5": 458.9, "25": 699.0, "50": 819.0, "75": 954.0, "95": 1361.2}, "umis_per_cell_percentiles": {"5": 1012.7, "25": 1779.2, "50": 2213.0, "75": 2766.8, "95": 4211.0}, "min_genes_threshold": 200, "fraction_cells_passing_min_genes": 1.0, "note": "QC thresholds are fixed by the analysis owner and are not agent-editable."}

**[ 19.95s] agent** -> `set_job_config("key": "species", "value": "human", "dry_run": false)`
  - hypothesis: Gene names are human-style (13 MT-, 0 mt-, 97.6% uppercase), so species should be human.

  - result: {"status": "applied", "job_id": "job-0005", "patch": {"species": "human"}, "relaunch_from": "qc"}

**[ 19.95s] agent** -> `request_relaunch()`
  - hypothesis: Species patched to human; relaunch should match MT- genes and pass QC.

**[ 20.07s] runner** relaunched from `qc` -> **SUCCEEDED**

  - result: {"job_id": "job-0005", "status": "succeeded", "from_step": "qc", "job_error": null, "failed_checks": [], "attempts_left": 2}

**[  23.0s] agent** -> `notify("message": "job-0005 (annotate) recovered: species was set to mouse but the genes are human (13 MT- genes, 0 mt-). Changed species to human, relaunched from qc, and the job succeeded.")`
  - hypothesis: Job recovered; report a one-line summary to on-call.

**[  23.0s] notify**: job-0005 (annotate) recovered: species was set to mouse but the genes are human (13 MT- genes, 0 mt-). Changed species to human, relaunched from qc, and the job succeeded.

  - result: {"sent": true}

_agent summary: I fixed job-0005: it had failed because its species setting was "mouse," but the gene names are human (13 genes start with `MT-`, none with `mt-`, and 97.6% are uppercase). I changed species to human and relaunched from qc, and the job succeeded with no failed checks and 2 relaunch attempts left._

**Outcome: FIXED**: applied: [{'key': 'species', 'new': 'human'}]
