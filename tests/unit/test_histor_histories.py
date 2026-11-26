import json

import pyarrow.parquet as pq
import pytest

from mcp_history_security.data.histor.histories import (
    reconstruct_histories,
    write_histories,
)
from mcp_history_security.data.histor.index import build_definition_index


def test_reconstruction_retains_reversion_and_missing_state(tmp_path) -> None:
    changes = tmp_path / "changes.jsonl"
    toolsets = tmp_path / "toolsets.jsonl"
    index = tmp_path / "index.sqlite"
    pairs = [("a", "b"), ("b", "a"), (None, "c")]
    events = []
    for number, (before, after) in enumerate(pairs, 1):
        events.append(
            {
                "id": number,
                "serverId": "server",
                "observedAt": f"2026-01-0{number}T00:00:00Z",
                "fromToolSetDigest": before,
                "toToolSetDigest": after,
                "summaryJson": json.dumps(
                    {"detail": "full", "modified": [{"tool": "tool"}]}
                ),
            }
        )
    changes.write_text("\n".join(map(json.dumps, events)) + "\n", encoding="utf-8")
    definitions = [
        {"digest": key, "toolsJson": json.dumps([{"name": "tool", "description": key}])}
        for key in ("a", "b", "c")
    ]
    toolsets.write_text(
        "\n".join(map(json.dumps, definitions)) + "\n", encoding="utf-8"
    )
    build_definition_index(changes, toolsets, index)
    histories = list(reconstruct_histories(changes, index))
    assert len(histories) == 1
    history = histories[0]["events"]
    assert history[0]["before_hash"] == history[1]["after_hash"]
    assert history[2]["before_status"] == "missing_digest"
    assert "server_chain_break_before" in history[2]["issues"]
    output = tmp_path / "histories.parquet"
    assert write_histories(changes, index, output) == {
        "histories": 1,
        "server_transition_entries": 3,
    }
    assert pq.read_table(output).num_rows == 1
    with pytest.raises(FileExistsError):
        write_histories(changes, index, output)
