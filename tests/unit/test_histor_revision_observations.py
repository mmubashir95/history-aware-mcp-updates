import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mcp_history_security.data.histor.revision_observations import (
    summarize_text_patterns,
    text_patterns,
)
from mcp_history_security.data.histor.sources import definition_hash


def test_text_patterns_do_not_claim_triviality() -> None:
    a = {"name": "t", "description": "Updated 2026-01-01", "inputSchema": {}}
    b = {"name": "t", "description": "Updated 2026-01-02", "inputSchema": {}}
    assert text_patterns(a, b) == {"iso_date_only_candidate"}
    assert text_patterns(a, {**a, "description": "Updated  2026-01-01"}) == {
        "whitespace_only_candidate"
    }
    assert not text_patterns(a, {**b, "inputSchema": {"type": "object"}})
    assert not text_patterns(a, {**a, "description": "Updated 2026-02-01 max 2"})


def test_revision_summary_reconciles_recorded_references(tmp_path) -> None:
    before = {"name": "t", "description": "Updated 2026-01-01"}
    after = {"name": "t", "description": "Updated 2026-01-02"}
    event = {
        "recorded_modification": True,
        "before_status": "present",
        "after_status": "present",
        "before_digest": "a",
        "after_digest": "b",
        "before_hash": definition_hash(before),
        "after_hash": definition_hash(after),
    }
    history = tmp_path / "history.parquet"
    toolsets = tmp_path / "toolsets.jsonl"
    output = tmp_path / "summary.json"
    pq.write_table(
        pa.Table.from_pylist([{"tool_name": "t", "events_json": json.dumps([event])}]),
        history,
    )
    toolsets.write_text(
        "".join(
            json.dumps({"digest": digest, "toolsJson": json.dumps([tool])}) + "\n"
            for digest, tool in (("a", before), ("b", after))
        ),
        encoding="utf-8",
    )
    result = summarize_text_patterns(history, toolsets, output)
    assert result["recorded_modifications"] == result["resolved_events"] == 1
    assert result["counts"] == {"iso_date_only_candidate": 1}
    event["after_hash"] = "0" * 64
    pq.write_table(
        pa.Table.from_pylist([{"tool_name": "t", "events_json": json.dumps([event])}]),
        history,
    )
    with pytest.raises(ValueError, match="reference missing"):
        summarize_text_patterns(history, toolsets, tmp_path / "invalid.json")
