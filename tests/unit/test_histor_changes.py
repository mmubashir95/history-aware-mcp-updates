import json

import pytest

from mcp_history_security.data.histor.changes import (
    change_version_metadata,
    modifications,
)


def test_modifications_keep_identity_and_ignore_additions(tmp_path) -> None:
    path = tmp_path / "changes.jsonl"
    record = {
        "id": 1,
        "serverId": "server-1",
        "observedAt": "2026-01-01T00:00:00Z",
        "fromToolSetDigest": "before",
        "toToolSetDigest": "after",
        "summaryJson": json.dumps(
            {"detail": "full", "added": ["new"], "modified": [{"tool": "existing"}]}
        ),
    }
    other = dict(record, id=2, serverId="server-2")
    path.write_text(
        "\n".join(map(json.dumps, [record, other])) + "\n", encoding="utf-8"
    )
    events = list(modifications(path))
    assert [(event.server_id, event.tool_name) for event in events] == [
        ("server-1", "existing"),
        ("server-2", "existing"),
    ]


def test_malformed_summary_has_context(tmp_path) -> None:
    path = tmp_path / "changes.jsonl"
    path.write_text('{"id": 17, "summaryJson": "["}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid change 17"):
        list(modifications(path))


def test_version_metadata_distinguishes_missing_and_null(tmp_path) -> None:
    path = tmp_path / "changes.jsonl"
    path.write_text(
        json.dumps({"id": 1, "fromPackageVersion": None}) + "\n", encoding="utf-8"
    )
    metadata = change_version_metadata(path)[1]
    assert metadata["fromPackageVersion"] is None
    assert "toPackageVersion" not in metadata
