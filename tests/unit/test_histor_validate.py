import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mcp_history_security.data.histor.validate import (
    compare_parquet,
    validate_tool_table,
)


def test_validator_checks_target_references(tmp_path) -> None:
    event = {
        "change_id": 1,
        "before_digest": "a",
        "after_digest": "b",
        "before_hash": "ha",
        "after_hash": "hb",
        "recorded_modification": True,
        "observed_at": "2026-01-01T00:00:00Z",
        "revision_kind": "substantive_uncertain",
        "issues": [],
    }
    states = [
        {
            "change_id": 1,
            "side": "before",
            "toolset_digest": "a",
            "definition_hash": "ha",
        },
        {
            "change_id": 1,
            "side": "after",
            "toolset_digest": "b",
            "definition_hash": "hb",
        },
    ]
    history = tmp_path / "history.parquet"
    output = tmp_path / "output.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [{"server_id": "s", "tool_name": "t", "events_json": json.dumps([event])}]
        ),
        history,
    )
    row = {
        "server_id": "s",
        "tool_name": "t",
        "target_change_id": 1,
        "target_before_digest": "a",
        "target_after_digest": "b",
        "max_eligible_k": 2,
        "windows_json": json.dumps({"2": {"eligible": True, "states": states}}),
    }
    pq.write_table(pa.Table.from_pylist([row]), output)
    assert validate_tool_table(history, output)["eligible_k2"] == 1
    row["target_before_digest"] = "wrong"
    pq.write_table(pa.Table.from_pylist([row]), output)
    with pytest.raises(ValueError, match="target reference mismatch"):
        validate_tool_table(history, output)


def test_reproducibility_compares_rows_not_filenames(tmp_path) -> None:
    left = tmp_path / "left.parquet"
    right = tmp_path / "right.parquet"
    pq.write_table(pa.Table.from_pylist([{"x": 1}]), left)
    pq.write_table(pa.Table.from_pylist([{"x": 1}]), right)
    assert compare_parquet(left, right) == {"identical": True, "rows_compared": 1}
    pq.write_table(pa.Table.from_pylist([{"x": 2}]), right)
    assert not compare_parquet(left, right)["identical"]
