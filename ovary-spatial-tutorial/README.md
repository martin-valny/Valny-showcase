# Mouse ovary spatial transcriptomics: a Seurat tutorial

An educational R Markdown notebook that walks through a complete Seurat analysis of **one published mouse ovary section** profiled with Curio Seeker 3×3 spatial transcriptomics.

## Data and citation

The data come from:

> Mantri M, Zhang HH, Spanos E, Ren YA, De Vlaminck I. **A spatiotemporal molecular atlas of the ovulating mouse ovary.** *Proc Natl Acad Sci USA* 121(5):e2317418121 (2024). https://doi.org/10.1073/pnas.2317418121

- Raw and processed data: NCBI GEO [**GSE240271**](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE240271). This tutorial uses sample **GSM7689281** (1 h after hCG) by default.
- The authors' analysis code and bead-location files: [madhavmantri/mouse_ovulation](https://github.com/madhavmantri/mouse_ovulation).

Please cite the paper if you use the data.

## What you will learn

| Section | You will… |
|---|---|
| Data loading | read an AnnData `.h5ad` in R with `rhdf5`, build a sparse count matrix and a Seurat object, attach bead x/y coordinates |
| Quality control | compute genes, UMIs and mito % per bead, choose thresholds, and see QC metrics on the tissue |
| Normalization | log-normalize counts and see why depth correction matters |
| Feature selection | pick highly variable genes (VST) |
| Spatially variable genes | score genes for spatial autocorrelation with Moran's I |
| Dimensionality reduction | run PCA, read an elbow plot, and build a UMAP |
| Clustering | build an SNN graph, run Louvain at several resolutions, and map clusters onto the tissue |
| Cell typing | score canonical ovary markers (oocyte, granulosa, cumulus, theca, stroma, smooth muscle, endothelium), read a DotPlot, and label clusters |
| Co-localization | measure which cell types are spatial neighbours (k-nearest-neighbour enrichment) |
| Differential expression | find cell-type markers with a Wilcoxon rank-sum test and draw a heatmap |

Each section ends with a short **Check your understanding** question on the biology, with the answer and explanation.

## How to run

**Reading is enough.** The notebook explains every step in prose and code. Knitting it yourself is optional and heavy: ~80,000 beads, several GB of RAM, and a long runtime.

To knit it locally:

```bash
# 1. R packages: nothing to do by hand. The first chunk of ovary_analysis.Rmd installs
#    whatever is missing (Seurat etc. from CRAN, rhdf5 from Bioconductor) when you knit.
#    Only rmarkdown is needed to start the knit:  Rscript -e 'install.packages("rmarkdown", repos="https://cloud.r-project.org")'

# 2. Data: download the GEO sample and convert it to data/sample.h5ad
pip install -r scripts/requirements.txt
python scripts/fetch_data.py

# 3. Knit
Rscript -e 'rmarkdown::render("ovary_analysis.Rmd")'
```

`scripts/fetch_data.py` documents the GEO URL. It checks that the file holds raw integer counts and writes exactly the layout the notebook reads (`/X` as CSR, `/obs/_index`, `/var/_index`, `/obsm/spatial`). It then prints a short HDF5 tree. Pass `--gsm`/`--file` to use another sample from GSE240271. If a sample's file has no spatial coordinates, pass `--coords` with the matching bead-location CSV from the authors' repository. The matrix is not committed (`data/*.h5ad` is gitignored).

**A note on cluster labels.** The `cluster_annotation` map in the Cell typing section is an example for this sample, written after looking at the marker plots. Cluster numbers can change with software versions even though the seed is fixed. Check the DotPlot and update the map if yours differ.

**What was checked when this repo was prepared:** every R chunk parses (`knitr::purl` + `parse`), and the fetch/convert script was tested on synthetic AnnData files. No knitted HTML is included, because the GEO file could not be downloaded in the environment used to prepare the repo. Knit it locally to see the figures.

## Disclaimer

This is an independent educational tutorial built on published, public data. It is not affiliated with the paper's authors or their institutions beyond citing their work, and it is not employer work. Thresholds and cell-type labels are teaching choices for one sample. They are not a re-analysis of, or claims beyond, the published study.
