# MCP History-Aware Security

Reproducible research code for an MS AI thesis on distinguishing legitimate
and malicious MCP tool updates using tool-version history. The project begins
with HISTOR data preparation and will later add MCPTox, labeling, baselines,
and history-aware models.

## Project status

The repository contains the Phase 0 foundation and an in-progress HISTOR
eligibility pipeline. A local HISTOR snapshot may be present under `data/raw/`;
raw data are not tracked in Git. Step 08 is not yet fully verified, and the
repository does not contain approved labels or trained models.

## Quick start

Install Python 3.11 or newer and [uv](https://docs.astral.sh/uv/getting-started/installation/), then install the project and development tools:

```bash
uv sync --group dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml
```

The dependency declarations in `pyproject.toml` include PyYAML and PyArrow
for the pipeline, plus pytest and Ruff for development. `uv` is installed
separately as the environment and package manager.

The last command validates configuration. Run it with `--help` to see the
available separately executable stages.

## Layout

| Path | Purpose |
| --- | --- |
| `configs/` | Versioned, non-secret data and experiment settings. |
| `data/` | Local datasets by lifecycle stage; contents are intentionally ignored. |
| `src/` | Importable, testable Python implementation. |
| `pipelines/` | Command-line workflow entry points. |
| `scanners/` | Third-party scanner integration. |
| `tests/` | Unit, integration, data-quality, and regression tests. |
| `artifacts/`, `reports/` | Generated results, ignored except for directory markers. |
| `docs/` | Thesis methodology, dataset notes, and decision records. |

See [the project-structure guide](docs/architecture/project_structure.md) for
the complete directory contract and [the HISTOR pipeline guide](docs/methodology/data_preparation.md)
for the intended workflow.

## Data policy

Never edit `data/raw/`. Raw data, intermediate data, processed datasets,
splits, checkpoints, embeddings, and predictions are excluded from Git.
Commit manifests, checksums, configuration, safe fixtures, code, and approved
aggregate reports instead. Respect each source dataset's license and do not
commit credentials.

## Development

Use a `src` layout and run tests before committing:

```bash
uv run pytest
uv run ruff check .
```

Architecture and research decisions belong in `docs/decisions/` as short ADRs.
