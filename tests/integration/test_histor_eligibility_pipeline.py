import json

import pyarrow.parquet as pq

from mcp_history_security.data.histor.annotations import write_annotation_coverage
from mcp_history_security.data.histor.assessment import write_assessments
from mcp_history_security.data.histor.classifications import (
    write_classification_coverage,
)
from mcp_history_security.data.histor.clusters import build_clusters
from mcp_history_security.data.histor.fields import write_field_coverage
from mcp_history_security.data.histor.histories import write_histories
from mcp_history_security.data.histor.index import build_definition_index
from mcp_history_security.data.histor.output import assemble_tool_table
from mcp_history_security.data.histor.scanner import write_scanner_coverage
from mcp_history_security.data.histor.validate import validate_tool_table


def test_end_to_end_reversion_is_reproducible(tmp_path) -> None:
    changes = tmp_path / "changes.jsonl"
    toolsets = tmp_path / "toolsets.jsonl"
    extras_changes = tmp_path / "extras_changes.jsonl"
    extras = tmp_path / "extras.jsonl"
    classifications = tmp_path / "classifications.jsonl"
    packages = tmp_path / "package_observations.jsonl"
    index = tmp_path / "index.sqlite"
    histories = tmp_path / "histories.parquet"
    assessment = tmp_path / "assessment.parquet"
    assessment2 = tmp_path / "assessment2.parquet"
    clusters = tmp_path / "clusters.parquet"
    annotations = tmp_path / "annotations.parquet"
    scanner = tmp_path / "scanner.parquet"
    fields = tmp_path / "fields.parquet"
    llm = tmp_path / "classifications.parquet"
    output = tmp_path / "eligibility.parquet"
    change_rows = []
    for index_num, (before, after) in enumerate(
        [("a", "b"), ("b", "a"), ("a", "c")], 1
    ):
        change_rows.append(
            {
                "id": index_num,
                "serverId": "s",
                "observedAt": f"2026-01-0{index_num}T00:00:00Z",
                "fromToolSetDigest": before,
                "toToolSetDigest": after,
                "summaryJson": json.dumps(
                    {"detail": "full", "modified": [{"tool": "t"}]}
                ),
            }
        )
    changes.write_text("\n".join(map(json.dumps, change_rows)) + "\n", encoding="utf-8")
    toolsets.write_text(
        "\n".join(
            json.dumps(
                {
                    "digest": value,
                    "toolsJson": json.dumps(
                        [{"name": "t", "description": value, "inputSchema": {}}]
                    ),
                }
            )
            for value in ("a", "b", "c")
        )
        + "\n",
        encoding="utf-8",
    )
    for path in (extras_changes, extras, classifications, packages):
        path.write_text("", encoding="utf-8")
    original = changes.read_bytes(), toolsets.read_bytes()
    build_definition_index(changes, toolsets, index)
    assert write_histories(changes, index, histories)["histories"] == 1
    metadata = {"s": {"source_type": "remote"}}
    scans = {"a": {}, "b": {}, "c": {}}
    write_assessments(histories, assessment, metadata, {}, scans)
    write_assessments(histories, assessment2, metadata, {}, scans)
    assert (
        pq.read_table(assessment).to_pylist() == pq.read_table(assessment2).to_pylist()
    )
    build_clusters(assessment, index, toolsets, clusters)
    write_annotation_coverage(assessment, changes, extras_changes, extras, annotations)
    write_scanner_coverage(histories, assessment, scanner, scans)
    write_field_coverage(assessment, index, toolsets, fields)
    write_classification_coverage(assessment, classifications, llm)
    result = assemble_tool_table(
        histories,
        assessment,
        clusters,
        annotations,
        scanner,
        fields,
        llm,
        packages,
        changes,
        output,
        "fixture",
    )
    assert result == {"candidate_tools": 1, "recorded_modifications": 3}
    assert validate_tool_table(histories, output)["eligible_k2"] == 1
    row = pq.read_table(output).to_pylist()[0]
    assert row["max_eligible_k"] == 4
    assert row["observed_reversions"] == 1
    assert row["substantive_version_states"] == 4
    assert (changes.read_bytes(), toolsets.read_bytes()) == original
