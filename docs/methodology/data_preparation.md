# HISTOR data preparation

## Pipeline contract

`pipelines/prepare_histor.py` is the single orchestrator for HISTOR
preparation. It must be safe to run in stages so changes to eligibility rules
do not require repeating expensive indexing or scanning work.

```text
validate source → audit changes → index toolsets → reconstruct histories
→ analyse revisions → validate scans → determine eligibility
→ deduplicate/extract sequences → produce a data-quality report
```

Run it with:

```bash
uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml
```

The entry point exposes independently runnable stages; use `--help` for their
arguments. The steps below use a new, empty output directory and reuse an
existing validated definition index. Outputs are never silently overwritten.

## Step 08 reproduction

Set `AUDIT_OUT` to the previous audit's `out` directory containing its
`02_parts`, `06_rescan` and original 03/04/05 outputs. Set `RUN_DIR` to a new
directory under `data/interim/histor/`. The commands intentionally do not edit
the snapshot. An existing index can be reused; to rebuild it, use the
`--build-definition-index` stage with a new index path.

```bash
AUDIT_OUT="/path/to/stage2_histor_audit/out"
RUN_DIR="data/interim/histor/eligibility/reproduction"
INDEX="data/interim/histor/indexed/definitions-step08-offset.sqlite"
mkdir -p "$RUN_DIR"
uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml \
  --validate-source --source-baseline "$RUN_DIR/source-baseline.json"
uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml \
  --reconstruct-histories --definition-index "$INDEX" \
  --history-output "$RUN_DIR/histories.parquet"
uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml \
  --revision-pattern-summary --history-input "$RUN_DIR/histories.parquet" \
  --revision-pattern-output "$RUN_DIR/revision_pattern_summary.json"
uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml \
  --assess-histories --history-input "$RUN_DIR/histories.parquet" \
  --rescan-dir "$AUDIT_OUT/06_rescan" --assessment-output "$RUN_DIR/assessment.parquet"
uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml \
  --build-clusters --assessment-input "$RUN_DIR/assessment.parquet" \
  --definition-index "$INDEX" --cluster-output "$RUN_DIR/duplicate_clusters.parquet"
uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml \
  --annotation-coverage --assessment-input "$RUN_DIR/assessment.parquet" \
  --annotation-output "$RUN_DIR/annotations.parquet"
uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml \
  --annotation-change-summary --assessment-input "$RUN_DIR/assessment.parquet" \
  --annotation-input "$RUN_DIR/annotations.parquet" \
  --annotation-change-output "$RUN_DIR/annotation_change_summary.json"
uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml \
  --field-coverage --assessment-input "$RUN_DIR/assessment.parquet" \
  --definition-index "$INDEX" --field-output "$RUN_DIR/fields.parquet"
uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml \
  --classification-coverage --assessment-input "$RUN_DIR/assessment.parquet" \
  --classification-output "$RUN_DIR/classifications.parquet"
uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml \
  --scanner-coverage --history-input "$RUN_DIR/histories.parquet" \
  --assessment-input "$RUN_DIR/assessment.parquet" --rescan-dir "$AUDIT_OUT/06_rescan" \
  --scanner-output "$RUN_DIR/scanner.parquet"
uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml \
  --assemble-tool-table --history-input "$RUN_DIR/histories.parquet" \
  --assessment-input "$RUN_DIR/assessment.parquet" --cluster-input "$RUN_DIR/duplicate_clusters.parquet" \
  --annotation-input "$RUN_DIR/annotations.parquet" --scanner-input "$RUN_DIR/scanner.parquet" \
  --field-input "$RUN_DIR/fields.parquet" --classification-input "$RUN_DIR/classifications.parquet" \
  --tool-table "$RUN_DIR/tool_eligibility.parquet"
uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml \
  --validate-tool-table --history-input "$RUN_DIR/histories.parquet" \
  --tool-table "$RUN_DIR/tool_eligibility.parquet"
uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml \
  --summarize --assessment-input "$RUN_DIR/assessment.parquet" \
  --cluster-input "$RUN_DIR/duplicate_clusters.parquet" --statistics-dir "$RUN_DIR"
mv "$RUN_DIR/history_length_distribution.csv" "$RUN_DIR/history_length_distribution_raw.csv"
uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml \
  --enrich-distribution --distribution-input "$RUN_DIR/history_length_distribution_raw.csv" \
  --tool-table "$RUN_DIR/tool_eligibility.parquet" \
  --distribution-output "$RUN_DIR/history_length_distribution.csv"
uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml \
  --selection-scenarios --assessment-input "$RUN_DIR/assessment.parquet" \
  --cluster-input "$RUN_DIR/duplicate_clusters.parquet" --scenario-output "$RUN_DIR/selection_scenarios.json"
uv run python pipelines/prepare_histor.py --config configs/data/histor.yaml \
  --research-report --tool-table "$RUN_DIR/tool_eligibility.parquet" \
  --history-input "$RUN_DIR/histories.parquet" --distribution-input "$RUN_DIR/history_length_distribution.csv" \
  --scenario-input "$RUN_DIR/selection_scenarios.json" --audit-dir "$AUDIT_OUT" \
  --definition-index "$INDEX" --annotation-change-input "$RUN_DIR/annotation_change_summary.json" \
  --revision-pattern-input "$RUN_DIR/revision_pattern_summary.json" \
  --report-output "$RUN_DIR/histor_eligibility_report.md"
```

Generate a manifest with `--write-manifest`, specifying `--source-baseline`,
`--history-input`, `--tool-table`, `--definition-index`, `--rescan-dir`,
`--audit-dir`, and each additional output via repeated `--artifact` arguments.
This manifest remains `verification_incomplete` until the full acceptance and
independent-review handoff are verified. Source hashes refer to local
decompressed bytes, not the manifest's compressed-file checksums.

Annotation change counts compare canonical annotation values for eligible
target pairs only when exact-time extras links establish both sides. Unknown or
unresolved links remain unknown. These counts do not include annotation-only
changes without a selected tool modification and do not create labels.
Whitespace and ISO-date pattern counts compare complete, source-resolved
definitions and count description-only patterns as candidates, not as trivial
or non-security-relevant edits. The ISO matcher does not cover all date formats.

## Configuration

`configs/data/histor.yaml` defines the snapshot path, output location,
eligibility constraints, sampling caps, and random seed. Never hardcode these
values in pipeline or model code. Proposed caps remain unset until the
eligibility analysis supplies evidence for them.

## Quality gates

Before moving data to `processed/`, validate continuity, version counts,
schema requirements, duplicate/template histories, scan linkage, and label
provenance. Record both passed and failed counts in a versioned manifest and
an approved data-quality report.
