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

The current entry point validates configuration only. Add each stage after the
corresponding audit code and its expected output have been preserved and tested.

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
