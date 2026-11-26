import hashlib
import json

import pytest

from mcp_history_security.data.histor.sources import (
    definition_hash,
    jsonl_records,
    validate_snapshot,
    write_source_baseline,
)


def test_definition_hash_preserves_missing_null_and_unicode() -> None:
    assert definition_hash({"name": "é", "x": None}) != definition_hash({"name": "é"})
    assert definition_hash({"name": "é"}) != definition_hash({"name": "e\u0301"})
    assert definition_hash({"a": 1, "b": 2}) == definition_hash({"b": 2, "a": 1})


def test_jsonl_reports_invalid_line(tmp_path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text(json.dumps({"id": 1}) + "\n{\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"records.jsonl:2: invalid JSON"):
        list(jsonl_records(path))


def test_jsonl_rejects_non_object(tmp_path) -> None:
    path = tmp_path / "records.jsonl"
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected JSON object"):
        list(jsonl_records(path))


def test_snapshot_checks_rows_and_correct_checksum_representation(tmp_path) -> None:
    (tmp_path / "changes.jsonl").write_text('{"id":1}\n', encoding="utf-8")
    (tmp_path / "record-set.json").write_text("{}", encoding="utf-8")
    manifest = {
        "type": "histor.dataset/v1",
        "createdAt": "2026-11-16T00:00:00Z",
        "files": {
            "changes.jsonl.gz": {"rows": 1, "sha256": "compressed-hash"},
            "record-set.json": {"sha256": hashlib.sha256(b"{}").hexdigest()},
        },
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result = validate_snapshot(tmp_path, "2026-11-16")
    assert (
        result["files"]["changes.jsonl"]["manifest_checksum_status"]
        == "compressed_only"
    )
    assert result["files"]["record-set.json"]["manifest_checksum_status"] == "verified"
    baseline = tmp_path / "baseline.json"
    write_source_baseline(baseline, result)
    assert (
        json.loads(baseline.read_text())["sha256"]["record-set.json"]
        == hashlib.sha256(b"{}").hexdigest()
    )
    with pytest.raises(FileExistsError):
        write_source_baseline(baseline, result)
    manifest["files"]["changes.jsonl.gz"]["rows"] = 2
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="expected 2 rows, found 1"):
        validate_snapshot(tmp_path, "2026-11-16")
