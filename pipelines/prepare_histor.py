#!/usr/bin/env python3
"""Validate and run the HISTOR preparation workflow.

Stages are deliberately introduced one at a time as audit scripts are migrated
into the package; this entry point prevents the workflow contract from drifting.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from mcp_history_security.data.histor.sources import (
    validate_snapshot,
    write_source_baseline,
)


def load_config(path: Path) -> dict:
    """Load and minimally validate a HISTOR pipeline configuration."""
    with path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict) or "dataset" not in config:
        raise ValueError("Configuration must contain a dataset mapping.")
    if not isinstance(config["dataset"], dict):
        raise ValueError("Configuration dataset must be a mapping.")
    for key in ("name", "raw_path", "output_path"):
        if key not in config["dataset"]:
            raise ValueError(f"dataset.{key} is required.")
    return config


def ensure_output_outside_raw(raw_path: Path, output_path: Path) -> None:
    """Reject generated paths that resolve inside the immutable snapshot."""
    if output_path.resolve().is_relative_to(raw_path.resolve()):
        raise ValueError(f"generated output cannot be inside raw data: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    stages = parser.add_mutually_exclusive_group()
    stages.add_argument(
        "--validate-source",
        action="store_true",
        help="stream and validate the configured snapshot without writing outputs",
    )
    stages.add_argument(
        "--reconstruct-histories",
        action="store_true",
        help="reconstruct candidate histories using an existing definition index",
    )
    stages.add_argument("--assess-histories", action="store_true")
    stages.add_argument("--build-definition-index", action="store_true")
    stages.add_argument("--build-clusters", action="store_true")
    stages.add_argument("--annotation-coverage", action="store_true")
    stages.add_argument("--annotation-change-summary", action="store_true")
    stages.add_argument("--revision-pattern-summary", action="store_true")
    stages.add_argument("--scanner-coverage", action="store_true")
    stages.add_argument("--field-coverage", action="store_true")
    stages.add_argument("--classification-coverage", action="store_true")
    stages.add_argument("--selection-scenarios", action="store_true")
    stages.add_argument("--summarize", action="store_true")
    stages.add_argument("--assemble-tool-table", action="store_true")
    stages.add_argument("--validate-tool-table", action="store_true")
    stages.add_argument("--research-report", action="store_true")
    stages.add_argument("--enrich-distribution", action="store_true")
    stages.add_argument("--write-manifest", action="store_true")
    stages.add_argument("--compare-parquet", action="store_true")
    stages.add_argument("--compare-definition-index", action="store_true")
    parser.add_argument("--definition-index", type=Path)
    parser.add_argument("--legacy-index", type=Path)
    parser.add_argument("--history-output", type=Path)
    parser.add_argument("--history-input", type=Path)
    parser.add_argument("--assessment-input", type=Path)
    parser.add_argument("--assessment-output", type=Path)
    parser.add_argument("--cluster-input", type=Path)
    parser.add_argument("--cluster-output", type=Path)
    parser.add_argument("--annotation-output", type=Path)
    parser.add_argument("--annotation-change-output", type=Path)
    parser.add_argument("--revision-pattern-output", type=Path)
    parser.add_argument("--scanner-output", type=Path)
    parser.add_argument("--field-output", type=Path)
    parser.add_argument("--classification-output", type=Path)
    parser.add_argument("--scenario-output", type=Path)
    parser.add_argument("--rescan-dir", type=Path)
    parser.add_argument("--statistics-dir", type=Path)
    parser.add_argument("--annotation-input", type=Path)
    parser.add_argument("--annotation-change-input", type=Path)
    parser.add_argument("--revision-pattern-input", type=Path)
    parser.add_argument("--scanner-input", type=Path)
    parser.add_argument("--field-input", type=Path)
    parser.add_argument("--classification-input", type=Path)
    parser.add_argument("--tool-table", type=Path)
    parser.add_argument("--distribution-input", type=Path)
    parser.add_argument("--distribution-output", type=Path)
    parser.add_argument("--scenario-input", type=Path)
    parser.add_argument("--audit-dir", type=Path)
    parser.add_argument("--report-output", type=Path)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--source-baseline", type=Path)
    parser.add_argument("--left-input", type=Path)
    parser.add_argument("--right-input", type=Path)
    parser.add_argument("--artifact", type=Path, action="append", default=[])
    parser.add_argument("--auxiliary-input", type=Path, action="append", default=[])
    args = parser.parse_args()
    config = load_config(args.config)
    dataset = config["dataset"]
    cache_bytes = dataset.get("index_cache_bytes", 67108864)
    if type(cache_bytes) is not int or cache_bytes < 0:
        raise ValueError("dataset.index_cache_bytes must be a nonnegative integer")
    outputs = [
        args.history_output,
        args.assessment_output,
        args.cluster_output,
        args.annotation_output,
        args.annotation_change_output,
        args.revision_pattern_output,
        args.scanner_output,
        args.field_output,
        args.classification_output,
        args.scenario_output,
        args.statistics_dir,
        args.distribution_output,
        args.report_output,
        args.manifest_output,
    ]
    if args.build_definition_index:
        outputs.append(args.definition_index)
    if args.validate_source:
        outputs.append(args.source_baseline)
    if args.assemble_tool_table:
        outputs.append(args.tool_table)
    for output in outputs:
        if output is not None:
            ensure_output_outside_raw(Path(dataset["raw_path"]), output)
    if args.validate_source:
        result = validate_snapshot(Path(dataset["raw_path"]), dataset["snapshot"])
        if args.source_baseline is not None:
            write_source_baseline(args.source_baseline, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    if args.build_definition_index:
        if args.definition_index is None:
            parser.error("--build-definition-index requires --definition-index")
        from mcp_history_security.data.histor.index import build_definition_index

        raw = Path(dataset["raw_path"])
        print(
            json.dumps(
                build_definition_index(
                    raw / "changes.jsonl", raw / "toolsets.jsonl", args.definition_index
                )
            )
        )
        return
    if args.reconstruct_histories:
        if args.definition_index is None or args.history_output is None:
            parser.error(
                "--reconstruct-histories requires "
                "--definition-index and --history-output"
            )
        from mcp_history_security.data.histor.histories import write_histories

        result = write_histories(
            Path(dataset["raw_path"]) / "changes.jsonl",
            args.definition_index,
            args.history_output,
            cache_bytes,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    if args.assess_histories:
        if any(
            value is None
            for value in (args.history_input, args.assessment_output, args.rescan_dir)
        ):
            parser.error(
                "--assess-histories requires --history-input, "
                "--assessment-output, and --rescan-dir"
            )
        from mcp_history_security.data.histor.assessment import write_assessments
        from mcp_history_security.data.histor.metadata import (
            launch_evidence,
            server_metadata,
        )
        from mcp_history_security.data.histor.scanner import load_rescans

        raw = Path(dataset["raw_path"])
        count = write_assessments(
            args.history_input,
            args.assessment_output,
            server_metadata(raw / "servers.jsonl"),
            launch_evidence(raw / "package_observations.jsonl"),
            load_rescans(args.rescan_dir),
        )
        print(json.dumps({"candidate_tools": count}))
        return
    if args.build_clusters:
        if any(
            value is None
            for value in (
                args.assessment_input,
                args.definition_index,
                args.cluster_output,
            )
        ):
            parser.error(
                "--build-clusters requires --assessment-input, "
                "--definition-index, and --cluster-output"
            )
        from mcp_history_security.data.histor.clusters import build_clusters

        print(
            json.dumps(
                build_clusters(
                    args.assessment_input,
                    args.definition_index,
                    Path(dataset["raw_path"]) / "toolsets.jsonl",
                    args.cluster_output,
                    cache_bytes,
                )
            )
        )
        return
    if args.annotation_coverage:
        if args.assessment_input is None or args.annotation_output is None:
            parser.error(
                "--annotation-coverage requires "
                "--assessment-input and --annotation-output"
            )
        from mcp_history_security.data.histor.annotations import (
            write_annotation_coverage,
        )

        raw = Path(dataset["raw_path"])
        result = write_annotation_coverage(
            args.assessment_input,
            raw / "changes.jsonl",
            raw / "extras_changes.jsonl",
            raw / "tool_extras.jsonl",
            args.annotation_output,
        )
        print(json.dumps(result))
        return
    if args.revision_pattern_summary:
        if args.history_input is None or args.revision_pattern_output is None:
            parser.error("--revision-pattern-summary requires history and output")
        from mcp_history_security.data.histor.revision_observations import (
            summarize_text_patterns,
        )

        result = summarize_text_patterns(
            args.history_input,
            Path(dataset["raw_path"]) / "toolsets.jsonl",
            args.revision_pattern_output,
        )
        print(json.dumps(result))
        return
    if args.annotation_change_summary:
        if any(
            value is None
            for value in (
                args.assessment_input,
                args.annotation_input,
                args.annotation_change_output,
            )
        ):
            parser.error(
                "--annotation-change-summary requires assessment, annotation "
                "coverage and output paths"
            )
        from mcp_history_security.data.histor.annotations import (
            summarize_target_annotation_changes,
        )

        result = summarize_target_annotation_changes(
            args.assessment_input,
            args.annotation_input,
            Path(dataset["raw_path"]) / "tool_extras.jsonl",
            args.annotation_change_output,
        )
        print(json.dumps(result))
        return
    if args.scanner_coverage:
        if any(
            value is None
            for value in (
                args.history_input,
                args.assessment_input,
                args.scanner_output,
                args.rescan_dir,
            )
        ):
            parser.error(
                "--scanner-coverage requires history, assessment, output, "
                "and rescan paths"
            )
        from mcp_history_security.data.histor.scanner import (
            load_recorded_scans,
            load_rescans,
            write_scanner_coverage,
        )

        result = write_scanner_coverage(
            args.history_input,
            args.assessment_input,
            args.scanner_output,
            load_rescans(args.rescan_dir),
            load_recorded_scans(Path(dataset["raw_path"]) / "scans.jsonl"),
        )
        print(json.dumps(result))
        return
    if args.field_coverage:
        if any(
            value is None
            for value in (
                args.assessment_input,
                args.definition_index,
                args.field_output,
            )
        ):
            parser.error(
                "--field-coverage requires assessment, index, and output paths"
            )
        from mcp_history_security.data.histor.fields import write_field_coverage

        print(
            json.dumps(
                write_field_coverage(
                    args.assessment_input,
                    args.definition_index,
                    Path(dataset["raw_path"]) / "toolsets.jsonl",
                    args.field_output,
                    cache_bytes,
                )
            )
        )
        return
    if args.classification_coverage:
        if args.assessment_input is None or args.classification_output is None:
            parser.error(
                "--classification-coverage requires assessment and output paths"
            )
        from mcp_history_security.data.histor.classifications import (
            write_classification_coverage,
        )

        print(
            json.dumps(
                write_classification_coverage(
                    args.assessment_input,
                    Path(dataset["raw_path"]) / "classifications.jsonl",
                    args.classification_output,
                )
            )
        )
        return
    if args.selection_scenarios:
        if any(
            value is None
            for value in (
                args.assessment_input,
                args.cluster_input,
                args.scenario_output,
            )
        ):
            parser.error(
                "--selection-scenarios requires assessment, cluster, and output paths"
            )
        from mcp_history_security.data.histor.statistics import (
            simulate_selection,
            write_scenarios,
        )

        sampling = config["sampling"]
        rows = simulate_selection(
            args.assessment_input,
            args.cluster_input,
            sampling["scenarios"],
            sampling["scenario_history_lengths"],
        )
        write_scenarios(args.scenario_output, rows)
        print(json.dumps({"scenario_rows": len(rows)}))
        return
    if args.summarize:
        if any(
            value is None
            for value in (
                args.assessment_input,
                args.cluster_input,
                args.statistics_dir,
            )
        ):
            parser.error(
                "--summarize requires --assessment-input, "
                "--cluster-input, and --statistics-dir"
            )
        from mcp_history_security.data.histor.statistics import summarize

        result = summarize(
            args.assessment_input, args.cluster_input, args.statistics_dir
        )
        print(
            json.dumps(
                {
                    "candidate_tools": result["candidate_tools"],
                    "max_eligible_k": result["max_eligible_k"],
                    "exclusion_reason_rows": len(result["exclusion_reasons"]),
                }
            )
        )
        return
    if args.assemble_tool_table:
        if any(
            value is None
            for value in (
                args.history_input,
                args.assessment_input,
                args.cluster_input,
                args.annotation_input,
                args.scanner_input,
                args.field_input,
                args.classification_input,
                args.tool_table,
            )
        ):
            parser.error(
                "--assemble-tool-table requires all seven input paths and --tool-table"
            )
        from mcp_history_security.data.histor.output import assemble_tool_table

        print(
            json.dumps(
                assemble_tool_table(
                    args.history_input,
                    args.assessment_input,
                    args.cluster_input,
                    args.annotation_input,
                    args.scanner_input,
                    args.field_input,
                    args.classification_input,
                    Path(dataset["raw_path"]) / "package_observations.jsonl",
                    Path(dataset["raw_path"]) / "changes.jsonl",
                    args.tool_table,
                    dataset["snapshot"],
                )
            )
        )
        return
    if args.validate_tool_table:
        if args.history_input is None or args.tool_table is None:
            parser.error(
                "--validate-tool-table requires --history-input and --tool-table"
            )
        from mcp_history_security.data.histor.validate import validate_tool_table

        print(json.dumps(validate_tool_table(args.history_input, args.tool_table)))
        return
    if args.research_report:
        if any(
            value is None
            for value in (
                args.tool_table,
                args.history_input,
                args.distribution_input,
                args.scenario_input,
                args.audit_dir,
                args.definition_index,
                args.report_output,
            )
        ):
            parser.error("--research-report requires all report inputs and output")
        from mcp_history_security.data.histor.report import write_research_report

        result = write_research_report(
            args.tool_table,
            args.history_input,
            args.distribution_input,
            args.scenario_input,
            args.audit_dir,
            Path(dataset["raw_path"]) / "manifest.json",
            args.definition_index,
            args.config,
            args.report_output,
            args.annotation_change_input,
            args.revision_pattern_input,
        )
        print(json.dumps(result))
        return
    if args.enrich_distribution:
        if any(
            value is None
            for value in (
                args.distribution_input,
                args.tool_table,
                args.distribution_output,
            )
        ):
            parser.error(
                "--enrich-distribution requires distribution, tool table and output"
            )
        from mcp_history_security.data.histor.statistics import (
            enrich_distribution_coverage,
        )

        print(
            json.dumps(
                enrich_distribution_coverage(
                    args.distribution_input, args.tool_table, args.distribution_output
                )
            )
        )
        return
    if args.write_manifest:
        if any(
            value is None
            for value in (
                args.manifest_output,
                args.source_baseline,
                args.tool_table,
                args.history_input,
            )
        ):
            parser.error(
                "--write-manifest requires manifest, baseline, "
                "tool table and history paths"
            )
        from mcp_history_security.data.histor.manifest import write_manifest
        from mcp_history_security.data.histor.validate import validate_tool_table

        counts = validate_tool_table(args.history_input, args.tool_table)
        limitations = [
            "Decompressed JSONL hashes cannot be verified against gzip hashes.",
            "Publisher prefixes and source types use current server metadata.",
            "Launch, annotation and scanner coverage may be unknown.",
            "Leakage clusters are approximate and do not prove independence.",
            "Independent review and complete acceptance verification are pending.",
        ]
        auxiliary = [args.history_input, *args.auxiliary_input]
        if args.definition_index is not None:
            auxiliary.append(args.definition_index)
        if args.rescan_dir is not None:
            auxiliary.extend(sorted(args.rescan_dir.glob("part*.jsonl")))
            auxiliary.extend(sorted(args.rescan_dir.glob("part*.ok")))
        if args.audit_dir is not None:
            auxiliary.extend(sorted((args.audit_dir / "02_parts").glob("part*.tsv.gz")))
            auxiliary.extend(
                args.audit_dir / name
                for name in (
                    "01_tool_mod_counts.tsv",
                    "03_scanner_candidates_full.jsonl",
                    "03_scanner_linkage_full.json",
                    "04_history_summary.json",
                    "04_tool_histories.tsv",
                    "05_revision_substance.json",
                )
            )
        result = write_manifest(
            args.manifest_output,
            Path(dataset["raw_path"]),
            args.source_baseline,
            args.config,
            [args.tool_table, *args.artifact],
            counts,
            limitations,
            auxiliary,
        )
        print(json.dumps({"status": result["status"], "counts": counts}))
        return
    if args.compare_parquet:
        if args.left_input is None or args.right_input is None:
            parser.error("--compare-parquet requires --left-input and --right-input")
        from mcp_history_security.data.histor.validate import compare_parquet

        result = compare_parquet(args.left_input, args.right_input)
        print(json.dumps(result))
        if not result["identical"]:
            raise SystemExit(1)
        return
    if args.compare_definition_index:
        if args.definition_index is None or args.legacy_index is None:
            parser.error("--compare-definition-index requires both index paths")
        from mcp_history_security.data.histor.index import compare_legacy_index

        result = compare_legacy_index(args.definition_index, args.legacy_index)
        print(json.dumps(result))
        if not result["identical"]:
            raise SystemExit(1)
        return
    print(f"Validated {dataset['name']} configuration: {args.config}")
    print("Select a stage with --help; Step 08 is not yet fully verified.")


if __name__ == "__main__":
    main()
