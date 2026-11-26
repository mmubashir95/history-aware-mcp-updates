import json
import shutil
import sqlite3

import pytest

from mcp_history_security.data.histor.index import (
    DefinitionStore,
    build_definition_index,
    compare_legacy_index,
)


def test_index_includes_intervening_states_and_duplicate_names(tmp_path) -> None:
    changes = tmp_path / "changes.jsonl"
    toolsets = tmp_path / "toolsets.jsonl"
    output = tmp_path / "index.sqlite"
    records = [
        {
            "id": 1,
            "serverId": "s",
            "observedAt": "2026-01-01T00:00:00Z",
            "fromToolSetDigest": "a",
            "toToolSetDigest": "b",
            "summaryJson": json.dumps({"detail": "full", "modified": [{"tool": "x"}]}),
        },
        {
            "id": 2,
            "serverId": "s",
            "observedAt": "2026-01-02T00:00:00Z",
            "fromToolSetDigest": "b",
            "toToolSetDigest": "c",
            "summaryJson": json.dumps({"detail": "full", "modified": []}),
        },
    ]
    changes.write_text("\n".join(map(json.dumps, records)) + "\n", encoding="utf-8")
    sets = [
        {"digest": "a", "toolsJson": json.dumps([{"name": "x"}])},
        {"digest": "b", "toolsJson": json.dumps([{"name": "x"}, {"name": "x"}])},
        {"digest": "c", "toolsJson": json.dumps([{"name": "x"}])},
    ]
    toolsets.write_text("\n".join(map(json.dumps, sets)) + "\n", encoding="utf-8")
    result = build_definition_index(changes, toolsets, output)
    assert result["found_digests"] == 3
    comparison = tmp_path / "comparison.sqlite"
    shutil.copyfile(output, comparison)
    assert compare_legacy_index(output, comparison)["identical"]
    with sqlite3.connect(comparison) as db:
        db.execute("UPDATE definitions SET occurrences = 3 WHERE digest = 'b'")
    assert not compare_legacy_index(output, comparison)["identical"]
    with sqlite3.connect(output) as db:
        assert db.execute(
            "SELECT occurrences FROM definitions WHERE digest = 'b' AND name = 'x'"
        ).fetchone() == (2,)
        columns = {row[1] for row in db.execute("PRAGMA table_info(definitions)")}
        assert "definition_json" not in columns
        assert "tool_ordinal" in columns
    with DefinitionStore(output, toolsets) as store:
        assert store.lookup("a", "x")[0] == "present"
        store.lookup("a", "x")[2]["name"] = "changed"
        assert store.lookup("a", "x")[2]["name"] == "x"
        assert store.lookup("b", "x")[0] == "ambiguous_name"
        assert store.lookup("a", "other")[0] == "absent"
        assert store.lookup(None, "x")[0] == "missing_digest"
        assert store.cache_bytes <= store.cache_limit_bytes
    with DefinitionStore(output, toolsets, cache_bytes=1) as store:
        assert store.lookup("a", "x")[0] == "present"
        assert store.cache_bytes == 0
    toolsets.write_text(
        toolsets.read_text().replace('"digest": "a"', '"digest": "z"', 1),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="source checksum does not match"):
        DefinitionStore(output, toolsets)
    with pytest.raises(FileExistsError):
        build_definition_index(changes, toolsets, output)


def test_incomplete_index_is_rejected(tmp_path) -> None:
    index = tmp_path / "incomplete.sqlite"
    toolsets = tmp_path / "toolsets.jsonl"
    toolsets.write_text("", encoding="utf-8")
    with sqlite3.connect(index) as db:
        db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO metadata VALUES ('schema_version', '2')")
    with pytest.raises(ValueError, match="incomplete or incompatible"):
        DefinitionStore(index, toolsets)
