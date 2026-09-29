# Walkthrough

Three investigations from `healpipe eval` on the real PBMC3k data (rules planner).
The Claude planner produces the same trace format. Only its hypotheses are its own words.

Each one follows the same arc. The **runner** reports a failed job. The
**sentinel** picks it up on its next poll and investigates with *that job type's*
tools only. It then patches config and asks the runner to relaunch, or it escalates.

Result lines are truncated at 400 characters.

## 1. Ingest recovery: matrix saved genes x cells

The load check sees gene names where cell barcodes should be. `inspect_matrix` (ingest kit) shows the barcodes are on the other axis. The sentinel patches `orientation`, and the runner resumes from `load`, the earliest step that key affects.

**[   0.0s] sentinel** picked up failed `ingest` job `job-0003` (rev 9)
  - symptom: `load.orientation`: 0% of observation names look like cell barcodes

**[   0.0s] agent** -> `inspect_job()`
  - hypothesis: start from the failed checks

  - result: {"id": "job-0003", "job_type": "ingest", "status": "failed", "error": "load.orientation: 0% of observation names look like cell barcodes", "failed_checks": [{"step": "load", "name": "orientation", "ok": false, "message": "0% of observation names look like cell barcodes", "metrics": {"obs_barcode_fraction": 0.0, "shape": [13714, 2638]}}], "config": {"species": "human", "input_scale": "counts", "ori

**[   0.0s] agent** -> `inspect_matrix()`
  - hypothesis: observations are not barcodes; maybe the matrix is transposed

  - result: {"shape_on_disk": [13714, 2638], "obs_name_examples": ["AL627309.1", "AP006222.2", "RP11-206L10.2", "RP11-206L10.9"], "var_name_examples": ["AAACATACAACCAC-1", "AAACATTGAGCTAC-1", "AAACATTGATCAGC-1", "AAACCGTGCTTCCG-1"], "obs_barcode_like_fraction": 0.0, "var_barcode_like_fraction": 1.0, "density": 0.0619, "n_nan": 0, "n_negative": 0, "min_nonzero": 1.0, "max": 419.0, "frac_nonzero_integer": 1.0}

**[  0.12s] agent** -> `set_job_config("key": "orientation", "value": "genes_x_cells", "dry_run": false)`
  - hypothesis: evidence points at orientation

  - result: {"status": "applied", "job_id": "job-0003", "patch": {"orientation": "genes_x_cells"}, "relaunch_from": "load"}

**[  0.12s] agent** -> `request_relaunch()`
  - hypothesis: verify the fix for ['orientation']

**[  0.56s] runner** relaunched from `load` -> **SUCCEEDED**

  - result: {"job_id": "job-0003", "status": "succeeded", "from_step": "load", "error": null, "failed_checks": [], "attempts_left": 2}

**[  0.56s] agent** -> `notify("message": "job-0003 recovered via [{'key': 'orientation', 'new': 'genes_x_cells'}]")`
  - hypothesis: close the loop

**[  0.56s] notify**: job-0003 recovered via [{'key': 'orientation', 'new': 'genes_x_cells'}]

  - result: {"sent": true}

**Outcome: FIXED**: applied: [{'key': 'orientation', 'new': 'genes_x_cells'}]

## 2. Annotate recovery: human sample registered as mouse

QC finds zero `mt-` genes. `inspect_gene_names` (annotate kit) shows uppercase symbols with 13 `MT-` genes. The sentinel patches `species`, and the runner resumes from `qc`, not `load`.

**[   0.0s] sentinel** picked up failed `annotate` job `job-0005` (rev 15)
  - symptom: `qc.mito_genes_detected`: 0 mitochondrial genes matched prefix 'mt-'

**[   0.0s] agent** -> `inspect_job()`
  - hypothesis: start from the failed checks

  - result: {"id": "job-0005", "job_type": "annotate", "status": "failed", "error": "qc.mito_genes_detected: 0 mitochondrial genes matched prefix 'mt-'", "failed_checks": [{"step": "qc", "name": "mito_genes_detected", "ok": false, "message": "0 mitochondrial genes matched prefix 'mt-'", "metrics": {"prefix": "mt-", "n_mito_genes": 0}}], "config": {"species": "mouse", "input_scale": "counts", "orientation": "c

**[   0.0s] agent** -> `inspect_gene_names()`
  - hypothesis: maybe the gene nomenclature does not match the configured species

  - result: {"n_genes": 13714, "examples": ["AL627309.1", "AP006222.2", "RP11-206L10.2", "MT-ND1", "MT-ND2", "MT-CO1"], "fraction_all_uppercase": 0.976, "fraction_titlecase": 0.023, "n_prefixed_MT-": 13, "n_prefixed_mt-": 0, "note": "Human symbols are conventionally uppercase (MT-CO1). Mouse symbols are title-case (mt-Co1)."}

**[  0.04s] agent** -> `set_job_config("key": "species", "value": "human", "dry_run": false)`
  - hypothesis: evidence points at species

  - result: {"status": "applied", "job_id": "job-0005", "patch": {"species": "human"}, "relaunch_from": "qc"}

**[  0.04s] agent** -> `request_relaunch()`
  - hypothesis: verify the fix for ['species']

**[  0.52s] runner** relaunched from `qc` -> **SUCCEEDED**

  - result: {"job_id": "job-0005", "status": "succeeded", "from_step": "qc", "error": null, "failed_checks": [], "attempts_left": 2}

**[  0.52s] agent** -> `notify("message": "job-0005 recovered via [{'key': 'species', 'new': 'human'}]")`
  - hypothesis: close the loop

**[  0.52s] notify**: job-0005 recovered via [{'key': 'species', 'new': 'human'}]

  - result: {"sent": true}

**Outcome: FIXED**: applied: [{'key': 'species', 'new': 'human'}]

## 3. Required escalation: library too shallow

Almost every cell fails the QC floor. The only thing that would make this job pass is a lower `min_genes`, and no job type can write that. The sentinel escalates with the depth numbers instead. This counts as a *correct* outcome in the eval.

**[   0.0s] sentinel** picked up failed `annotate` job `job-0006` (rev 18)
  - symptom: `qc.cells_retained`: 8/2638 cells (0%) passed QC

**[   0.0s] agent** -> `inspect_job()`
  - hypothesis: start from the failed checks

  - result: {"id": "job-0006", "job_type": "annotate", "status": "failed", "error": "qc.cells_retained: 8/2638 cells (0%) passed QC", "failed_checks": [{"step": "qc", "name": "cells_retained", "ok": false, "message": "8/2638 cells (0%) passed QC", "metrics": {"n_in": 2638, "n_out": 8, "fraction": 0.003}}], "config": {"species": "human", "input_scale": "counts", "orientation": "cells_x_genes", "min_genes": 200

**[   0.0s] agent** -> `inspect_qc_distribution()`
  - hypothesis: most cells fail QC: bad config or bad library?

  - result: {"n_cells": 2638, "genes_per_cell_percentiles": {"5": 35.0, "25": 59.0, "50": 73.0, "75": 89.0, "95": 131.0}, "umis_per_cell_percentiles": {"5": 40.0, "25": 70.0, "50": 89.0, "75": 112.0, "95": 174.0}, "min_genes_threshold": 200, "fraction_cells_passing_min_genes": 0.003, "note": "QC thresholds are fixed by the analysis owner and are not agent-editable."}

**[  0.03s] agent** -> `escalate("reason": "library too shallow: most cells are below the QC floor, and thresholds are not agent-editable", "evidence": "{\"n_cells\": 2638, \"genes_per_cell_percentiles\": {\"5\": 35.0, \"25\": 59.0, \"50\": 73.0, \"75\": 89.0, \"95\": 131.0}, \"umis_per_cell_percentiles\": {\"5\": 40.0, \"25\": 70.0, \"50\": 89.0, \"75\": 112.0, \"95\": 174.0}, \"min_genes_threshold\": 200, \"fraction_cells_passing_min_genes\": 0.003, \"note\": \"QC thresholds are fixed by the analysis owner and are not agent-editable.\"}")`
  - hypothesis: library too shallow: most cells are below the QC floor, and thresholds are not agent-editable

  - result: {"escalated": true, "message": "A human has been paged. Stop here."}

**Outcome: ESCALATED**: library too shallow: most cells are below the QC floor, and thresholds are not agent-editable

## Shadow mode (`--dry-run`)

`healpipe run --scenario species_mislabel --dry-run` runs the same investigation, but every write becomes `would_apply` and relaunch is disabled. The job stays `failed` with its config unchanged. The outcome is `proposed`, and it is not marked processed, so a live sentinel will still handle it.

```
set_job_config(species=human, dry_run=false)
  -> {"status": "would_apply", "patch": {"species": "human"}, "note": "shadow mode: write converted to dry-run"}
Outcome: PROPOSED
```
