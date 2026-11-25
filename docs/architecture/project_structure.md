# Project structure

## Purpose

This repository follows a pragmatic combination of the `src` Python package layout, Cookiecutter Data Science-style data stages, and configuration-driven research workflows. Its goal is reproducibility without prematurely adding services, databases, or a fixed neural architecture.

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

Empty directories have `.gitkeep` markers only where the directory itself is part of the repository contract. Generated contents remain untracked.

## Data lifecycle

`raw` is immutable source material. `interim` contains derived working data; `annotations` holds review queues and label decisions; `processed` contains validated versioned datasets; `splits` contains model-ready partitions.

Each published dataset version must include a manifest with source identity, checksums, preparation configuration, creation time, schema version, and row counts. Keep manifest metadata in Git, but keep redistributable or sensitive data out of Git unless licensing explicitly permits it.

## Module migration

Exploratory numbered HISTOR scripts should be frozen with their outputs before their logic is migrated. The destination modules are:

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

## Proposed complete layout

This is a planning map, not a claim that every file exists or that later
research phases are approved. Create modules when their phase is authorized;
do not create placeholder implementations merely to fill the tree.

```text
.github/workflows/ci.yml
configs/{data,labeling,models,experiments}/
data/
  raw/{histor,mcptox,msb}/
  external/{capgate,guardbee}/
  interim/histor/{indexed,histories,scanner_findings,eligibility,sequences}/
  interim/mcptox/compatible_attacks/
  interim/constructed/{benign,malicious}/
  annotations/{review_queues,reviewer_annotations,adjudicated_labels}/
  processed/<dataset-version>/{dataset.parquet,dataset_card.md,manifest.json}
  splits/<dataset-version>/{train.parquet,validation.parquet,test.parquet}
  manifests/
src/mcp_history_security/
  data/{histor,mcptox,construction,labeling,validation,splitting}/
  features/  models/{baselines,history_aware}/  training/  evaluation/
  inference/  utils/
pipelines/{prepare_histor,prepare_mcptox,prepare_labels,prepare_dataset,train,evaluate}.py
scanners/warden/{package.json,package-lock.json,rescan.mjs}
notebooks/{histor,mcptox,dataset_analysis,model_analysis}/
experiments/{latest_only,pairwise,first_to_last,history_aware,ablation}/
tests/{unit,integration,data_quality,regression,fixtures}/
artifacts/{checkpoints,embeddings,predictions,metrics}/
reports/{data_audit,data_quality,labeling,evaluation,figures,implementation,reviews}/
docs/{architecture,methodology,datasets,labeling,decisions,research}/
README.md  pyproject.toml  uv.lock  Makefile  .gitignore  .env.example
.pre-commit-config.yaml  AGENTS.md  CLAUDE.md
```

The example HISTOR snapshot is `data/raw/histor/2026-11-16/`, with
`manifest.json`, `servers.jsonl`, `changes.jsonl`, `toolsets.jsonl`,
`scans.jsonl`, `classifications.jsonl`, `tool_extras.jsonl`,
`extras_changes.jsonl`, `package_observations.jsonl`, `pattern-set.json`,
and `record-set.json`. These names are proposed inputs and must be checked
against the actual snapshot before implementation.

## Planned modules and workflow

The HISTOR package may contain `ingestion.py`, `changes_audit.py`,
`toolset_index.py`, `scanner_linkage.py`, `history_reconstruction.py`,
`revision_analysis.py`, `rescan_validation.py`, `eligibility.py`,
`deduplication.py`, `sequence_extraction.py`, and `statistics.py`. The
configurable pipeline is intended to validate sources, audit changes, index
toolsets, reconstruct histories, analyze revisions, validate scans, assess
eligibility, deduplicate and extract sequences, and report data quality.
Individual stages should eventually be runnable independently.

Potential labeling modules are `review_queue.py`, `sampling.py`,
`presumed_labels.py`, `human_review.py`, `adjudication.py`, `agreement.py`,
`label_validation.py`, and `provenance.py`. The codebook and future annotation
guidelines, borderline cases, and validation protocol belong in
`docs/labeling/`.

Potential feature modules cover text, schema, transitions, and time. Baseline
models may cover latest-only, pairwise, and first-to-last inputs; history-aware
models may use an encoder, GRU, temporal attention, and classifier. Training
may include dataset, trainer, losses, and callbacks modules; evaluation may
include metrics, history length, ablation, external validation, leakage checks,
and error analysis. These names and architectures remain provisional until
dataset feasibility and the research design are approved.

## Configuration, testing, and tooling

Keep snapshot paths, eligibility rules, sequence lengths, sampling caps, and
random seeds in versioned configuration. The proposed example uses snapshot
`2026-11-16`, minimum two versions, primary history length four, and seed 42;
continuity, reversions, schema changes, hidden characters, and template
duplicates require explicit handling. Server and publisher caps remain
undecided pending evidence. These are proposals, not approved research rules.

Testing spans unit, integration, data quality, frozen-snapshot regression,
leakage, label validation, model input and masking, and reproducibility
checks, as applicable to each phase. Proposed tooling includes Python, uv,
pytest, JSONL and Parquet, with pandas or DuckDB as needed; scikit-learn,
PyTorch, Transformers, and MLflow are later options. Ruff, type checking,
GitHub Actions, manifests, and optionally DVC or Docker support reproducibility.
Add dependencies only when justified.

## Phase roadmap and preservation

The proposed sequence is Phase 0 repository foundation; Phase 1 migration and
verification of existing HISTOR audits; Phase 2 eligibility and sequence
preparation; Phase 3 labeling; Phase 4 MCPTox integration; Phase 5 final dataset
and leakage prevention; Phase 6 baselines; Phase 7 history-aware model; and
Phase 8 evaluation and inference. The proposal prioritizes phases 0–2; actual
execution remains subject to the owner's approved scope.

Before migration, locate and preserve the original scripts, snapshot identity,
outputs, and independently verified audit results. Compare migrated behavior
against those records without overwriting them. Record missing evidence and
unverified counts rather than treating the proposed script list as proof of
what exists locally. Research questions, scope, dataset notes, methodology,
codebook, and decision records should be added as their decisions mature.
