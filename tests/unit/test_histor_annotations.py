import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mcp_history_security.data.histor.annotations import (
    annotation_fingerprint,
    annotation_status,
    annotation_transition,
    summarize_target_annotation_changes,
    write_annotation_coverage,
)


def test_annotation_presence_states_are_distinct() -> None:
    assert annotation_status({"tools": {}}, "t") == "absent"
    assert annotation_status({"tools": {"t": {"annotations": None}}}, "t") == "null"
    assert annotation_status({"tools": {"t": {"annotations": {}}}}, "t") == "empty"
    assert annotation_status({"tools": {"t": {"annotations": []}}}, "t") == "malformed"
    assert (
        annotation_status(
            {"tools": {"t": {"annotations": {"readOnlyHint": False}}}}, "t"
        )
        == "present"
    )
    with pytest.raises(ValueError):
        annotation_status({"tools": []}, "t")


def test_coverage_uses_only_exact_extra_change_links(tmp_path) -> None:
    assessment = tmp_path / "assessment.parquet"
    changes = tmp_path / "changes.jsonl"
    extras_changes = tmp_path / "extras_changes.jsonl"
    extras = tmp_path / "extras.jsonl"
    output = tmp_path / "coverage.parquet"
    windows = {
        "2": {
            "states": [
                {"change_id": 1, "side": "before"},
                {"change_id": 1, "side": "after"},
            ]
        }
    }
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "server_id": "s",
                    "tool_name": "t",
                    "max_eligible_k": 2,
                    "windows_json": json.dumps(windows),
                }
            ]
        ),
        assessment,
    )
    changes.write_text(
        json.dumps({"id": 1, "serverId": "s", "observedAt": "time"}) + "\n",
        encoding="utf-8",
    )
    extras_changes.write_text(
        json.dumps(
            {
                "serverId": "s",
                "observedAt": "time",
                "fromExtrasDigest": None,
                "toExtrasDigest": "d",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    extras.write_text(
        json.dumps(
            {
                "digest": "d",
                "extrasJson": json.dumps({"tools": {"t": {"annotations": {}}}}),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert write_annotation_coverage(
        assessment, changes, extras_changes, extras, output
    ) == {"selected_states": 2, "unknown_or_unresolved": 1}
    rows = pq.read_table(output).to_pylist()
    assert [row["annotation_status"] for row in rows] == ["unknown", "empty"]


def test_annotation_comparison_retains_unknown_and_absent(tmp_path) -> None:
    absent = annotation_fingerprint({"tools": {}}, "t")
    empty = annotation_fingerprint({"tools": {"t": {"annotations": {}}}}, "t")
    assert annotation_transition(absent, empty) == "changed"
    assert annotation_transition(empty, empty) == "unchanged"
    assert annotation_transition(None, empty) == "unknown"

    assessment = tmp_path / "assessment.parquet"
    coverage = tmp_path / "coverage.parquet"
    extras = tmp_path / "extras.jsonl"
    output = tmp_path / "summary.json"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "server_id": "s",
                    "tool_name": "t",
                    "source_type": "remote",
                    "target_change_id": 1,
                    "max_eligible_k": 2,
                },
                {
                    "server_id": "s",
                    "tool_name": "u",
                    "source_type": "remote",
                    "target_change_id": 2,
                    "max_eligible_k": 2,
                },
            ]
        ),
        assessment,
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "server_id": "s",
                    "tool_name": "t",
                    "change_id": 1,
                    "side": "before",
                    "annotation_status": "absent",
                    "extras_digest": "",
                },
                {
                    "server_id": "s",
                    "tool_name": "t",
                    "change_id": 1,
                    "side": "after",
                    "annotation_status": "empty",
                    "extras_digest": "d",
                },
                {
                    "server_id": "s",
                    "tool_name": "u",
                    "change_id": 2,
                    "side": "before",
                    "annotation_status": "unknown",
                    "extras_digest": None,
                },
                {
                    "server_id": "s",
                    "tool_name": "u",
                    "change_id": 2,
                    "side": "after",
                    "annotation_status": "absent",
                    "extras_digest": "",
                },
            ]
        ),
        coverage,
    )
    extras.write_text(
        json.dumps(
            {
                "digest": "d",
                "extrasJson": json.dumps({"tools": {"t": {"annotations": {}}}}),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = summarize_target_annotation_changes(assessment, coverage, extras, output)
    assert result["counts"]["all"] == {"changed": 1, "unknown": 1}
    rows = pq.read_table(coverage).to_pylist()
    rows[1]["annotation_status"] = "present"
    pq.write_table(pa.Table.from_pylist(rows), coverage)
    with pytest.raises(ValueError, match="coverage disagrees"):
        summarize_target_annotation_changes(
            assessment, coverage, extras, tmp_path / "invalid-summary.json"
        )
