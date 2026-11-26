import hashlib
import json

import pytest

from mcp_history_security.data.histor.manifest import write_manifest


def test_manifest_refuses_changed_raw_input(tmp_path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "manifest.json").write_text("{}", encoding="utf-8")
    (raw / "data.jsonl").write_text("{}\n", encoding="utf-8")
    baseline = {
        "snapshot": "example",
        "manifest_sha256": hashlib.sha256(b"{}").hexdigest(),
        "sha256": {"data.jsonl": "wrong"},
    }
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    with pytest.raises(ValueError, match="raw source changed"):
        write_manifest(
            tmp_path / "output.json",
            raw,
            baseline_path,
            tmp_path / "config",
            [],
            {},
            [],
        )
    assert not (tmp_path / "output.json").exists()
