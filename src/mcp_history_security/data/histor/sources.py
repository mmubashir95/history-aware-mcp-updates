"""Read and validate immutable HISTOR snapshot inputs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path


def jsonl_records(path: Path) -> Iterator[dict]:
    """Stream JSON objects, identifying the file and line of malformed records."""
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: expected JSON object")
            yield value


def sha256_file(path: Path) -> str:
    """Hash the bytes actually present, without loading the file into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def definition_hash(tool: dict) -> str:
    """Hash the complete JSON tool object while preserving Unicode and nulls."""
    content = json.dumps(
        tool, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def validate_snapshot(path: Path, snapshot: str) -> dict:
    """Validate manifest references and stream every source record.

    Manifest hashes for gzip files cannot authenticate decompressed JSONL bytes;
    the calculated hashes are recorded independently for reproducibility.
    """
    manifest_path = path / "manifest.json"
    with manifest_path.open(encoding="utf-8") as stream:
        manifest = json.load(stream)
    if not isinstance(manifest, dict) or manifest.get("type") != "histor.dataset/v1":
        raise ValueError(f"{manifest_path}: unsupported HISTOR manifest")
    if not str(manifest.get("createdAt", "")).startswith(snapshot):
        raise ValueError(f"{manifest_path}: snapshot does not match {snapshot}")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError(f"{manifest_path}: missing files mapping")
    results = {}
    for source_name, metadata in sorted(files.items()):
        if not isinstance(metadata, dict):
            raise ValueError(f"{manifest_path}: invalid metadata for {source_name}")
        local_name = source_name.removesuffix(".gz")
        if Path(local_name).name != local_name:
            raise ValueError(f"{manifest_path}: invalid input filename {source_name!r}")
        source = path / local_name
        if not source.is_file():
            raise FileNotFoundError(f"HISTOR source not found: {source}")
        actual_hash = sha256_file(source)
        result = {"sha256": actual_hash, "bytes": source.stat().st_size}
        if source_name.endswith(".jsonl.gz"):
            rows = sum(1 for _ in jsonl_records(source))
            if rows != metadata.get("rows"):
                raise ValueError(
                    f"{source}: expected {metadata.get('rows')} rows, found {rows}"
                )
            result.update(rows=rows, manifest_checksum_status="compressed_only")
        elif source_name.endswith(".json"):
            with source.open(encoding="utf-8") as stream:
                json.load(stream)
            if actual_hash != metadata.get("sha256"):
                raise ValueError(f"{source}: SHA-256 does not match manifest")
            result["manifest_checksum_status"] = "verified"
        else:
            raise ValueError(f"{manifest_path}: unsupported source {source_name}")
        results[local_name] = result
    return {
        "snapshot": snapshot,
        "manifest_sha256": sha256_file(manifest_path),
        "files": results,
    }


def write_source_baseline(path: Path, validation: dict) -> None:
    """Persist checksums of the actual local bytes, not the compressed manifest."""
    baseline = {
        "snapshot": validation["snapshot"],
        "manifest_sha256": validation["manifest_sha256"],
        "representation": "actual local uncompressed files",
        "sha256": {name: info["sha256"] for name, info in validation["files"].items()},
    }
    with path.open("x", encoding="utf-8") as stream:
        json.dump(baseline, stream, indent=2, sort_keys=True)
        stream.write("\n")
