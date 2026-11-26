import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mcp_history_security.data.histor.scanner import (
    compare_findings,
    compare_recorded_spans,
    load_rescans,
    write_scanner_coverage,
)


def test_missing_scans_differ_from_clean_and_findings_are_compared(tmp_path) -> None:
    shard = tmp_path / "part00.jsonl"
    records = [
        {"toolSetDigest": "a", "ruleset": "r", "findings": []},
        {
            "toolSetDigest": "b",
            "ruleset": "r",
            "findings": [
                {
                    "tool": "x",
                    "code": "C",
                    "tier": "block",
                    "message": 'Tool "x" description test',
                }
            ],
        },
    ]
    shard.write_text("\n".join(map(json.dumps, records)) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="completion marker"):
        load_rescans(tmp_path)
    (tmp_path / "part00.ok").touch()
    scans = load_rescans(tmp_path)
    assert compare_findings(scans, "a", "missing", "x")["new"] is None
    assert compare_findings(scans, "a", "a", "x")["new"] == 0
    assert compare_findings(scans, "a", "b", "x")["new"] == 1


def test_duplicate_finding_instances_are_counted() -> None:
    finding = {
        "identity": ("C", "description"),
        "span_hash": "f",
        "tier": "block",
        "code": "C",
    }
    scans = {"a": {"x": [finding]}, "b": {"x": [finding, finding]}}
    result = compare_findings(scans, "a", "b", "x")
    assert result["persistent"] == 1
    assert result["new"] == 1


def test_changed_finding_message_is_persistent() -> None:
    old = {"identity": ("C", "description"), "span_hash": "old", "tier": "block"}
    new = {"identity": ("C", "description"), "span_hash": "new", "tier": "block"}
    result = compare_findings({"a": {"x": [old]}, "b": {"x": [new]}}, "a", "b", "x")
    assert result["persistent"] == 1
    assert result["persistent_message_changed"] == 1
    assert result["new"] == 0


def test_unresolved_scanner_location_is_not_called_new_or_persistent() -> None:
    finding = {"identity": ("C", None), "span_hash": "a", "tier": "block"}
    result = compare_findings({"a": {}, "b": {"t": [finding]}}, "a", "b", "t")
    assert result["coverage"] == "both_scanned"
    assert result["linkage"] == "unresolved_location"
    assert result["new"] is None


def test_recorded_span_changes_require_both_scans() -> None:
    scans = {
        "a": {"x": [{"code": "C", "where": "d", "span_hash": "one"}]},
        "b": {"x": [{"code": "C", "where": "d", "span_hash": "two"}]},
    }
    assert compare_recorded_spans(scans, "a", "b", "x")["changed_code_locations"] == 1
    assert (
        compare_recorded_spans(scans, "a", "missing", "x")["changed_code_locations"]
        is None
    )


def test_reintroduced_finding_requires_prior_coverage(tmp_path) -> None:
    finding = {
        "identity": ("C", "description"),
        "span_hash": "f",
        "tier": "block",
        "code": "C",
    }
    scans = {"a": {"t": [finding]}, "b": {}, "c": {"t": [finding]}}
    events = [
        {"change_id": 1, "before_digest": "a", "after_digest": "b"},
        {"change_id": 2, "before_digest": "b", "after_digest": "c"},
    ]
    history = tmp_path / "history.parquet"
    assessment = tmp_path / "assessment.parquet"
    output = tmp_path / "coverage.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [{"server_id": "s", "tool_name": "t", "events_json": json.dumps(events)}]
        ),
        history,
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "server_id": "s",
                    "tool_name": "t",
                    "target_change_id": 2,
                    "max_eligible_k": 0,
                    "windows_json": "{}",
                }
            ]
        ),
        assessment,
    )
    assert (
        write_scanner_coverage(history, assessment, output, scans)["candidate_tools"]
        == 1
    )
    row = pq.read_table(output).to_pylist()[0]
    assert row["target_reintroduced"] == 1
    assert row["prior_coverage_complete"] is True
    assert row["earlier_findings_status"] == "observed"
