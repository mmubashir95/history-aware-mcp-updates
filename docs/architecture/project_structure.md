# Project structure

## Purpose

This repository follows a pragmatic combination of the `src` Python package
layout, Cookiecutter Data Science-style data stages, and configuration-driven
research workflows. Its goal is reproducibility without prematurely adding
services, databases, or a fixed neural architecture.

## Directory contract

```text
configs/       Versioned data, labeling, model, and experiment settings.
data/          Local data grouped as raw, external, interim, annotations,
               processed, splits, and manifests.
src/           Reusable implementation package: data, features, models,
               training, evaluation, inference, and utilities.
pipelines/     Thin CLI entry points that coordinate package modules.
scanners/      Pinned integrations for external security scanners.
notebooks/     Exploratory analysis only; promoted logic belongs in src/.
experiments/   Reproducible experiment definitions and notes.
tests/         Unit, integration, data-quality, regression, and fixtures.
artifacts/     Generated checkpoints, embeddings, predictions, and metrics.
reports/       Approved audits, quality reports, evaluations, and figures.
docs/          Methodology, dataset documentation, codebooks, and ADRs.
```

Empty directories have `.gitkeep` markers only where the directory itself is
part of the repository contract. Generated contents remain untracked.

## Data lifecycle

`raw` is immutable source material. `interim` contains derived working data;
`annotations` holds review queues and label decisions; `processed` contains
validated versioned datasets; `splits` contains model-ready partitions.

Each published dataset version must include a manifest with source identity,
checksums, preparation configuration, creation time, schema version, and row
counts. Keep manifest metadata in Git, but keep redistributable or sensitive
data out of Git unless licensing explicitly permits it.

## Module migration

Exploratory numbered HISTOR scripts should be frozen with their outputs before
their logic is migrated. The destination modules are:

| Exploratory script | Package module |
| --- | --- |
| `01_changes_audit.py` | `data/histor/changes_audit.py` |
| `02_toolset_index.py` | `data/histor/toolset_index.py` |
| `03_scanner_linkage.py` | `data/histor/scanner_linkage.py` |
| `04_tool_histories.py` | `data/histor/history_reconstruction.py` |
| `05_revision_substance.py` | `data/histor/revision_analysis.py` |
| `07_compare_rescan.py` | `data/histor/rescan_validation.py` |
| `08_eligibility.py` | `data/histor/eligibility.py` |

The Warden rescanner belongs at `scanners/warden/rescan.mjs`.
