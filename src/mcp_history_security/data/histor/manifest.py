"""Write auditable processing manifests without claiming unverified completion."""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .sources import sha256_file


def write_manifest(
    path: Path,
    snapshot_dir: Path,
    baseline_path: Path,
    config_path: Path,
    outputs: list[Path],
    counts: dict,
    limitations: list[str],
    auxiliary_inputs: list[Path] | None = None,
) -> dict:
    """Verify raw hashes and write a manifest marked verification-incomplete."""
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    sources = {}
    if sha256_file(snapshot_dir / "manifest.json") != baseline["manifest_sha256"]:
        raise ValueError("raw source manifest changed since baseline")
    for name, expected in sorted(baseline["sha256"].items()):
        if Path(name).name != name:
            raise ValueError("invalid baseline input name")
        actual = sha256_file(snapshot_dir / name)
        if actual != expected:
            raise ValueError(f"raw source changed since baseline: {name}")
        sources[name] = {"sha256": actual, "representation": "local uncompressed bytes"}
    artifacts = {}
    for output in outputs:
        if not output.is_file():
            raise FileNotFoundError(f"missing expected output: {output}")
        artifacts[str(output)] = {
            "sha256": sha256_file(output),
            "bytes": output.stat().st_size,
        }
    inputs = {}
    for auxiliary in auxiliary_inputs or []:
        if not auxiliary.is_file():
            raise FileNotFoundError(f"missing auxiliary input: {auxiliary}")
        inputs[str(auxiliary)] = {
            "sha256": sha256_file(auxiliary),
            "bytes": auxiliary.stat().st_size,
        }
    configuration = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    code_paths = sorted(Path("src/mcp_history_security/data/histor").glob("*.py")) + [
        Path("pipelines/prepare_histor.py"),
        config_path,
    ]
    manifest = {
        "status": "verification_incomplete",
        "snapshot": baseline["snapshot"],
        "generated_at": datetime.now(UTC).isoformat(),
        "source_manifest_sha256": baseline["manifest_sha256"],
        "sources": sources,
        "auxiliary_inputs": inputs,
        "outputs": artifacts,
        "config_path": str(config_path),
        "configuration": configuration,
        "git_revision": revision,
        "working_code_sha256": {str(code): sha256_file(code) for code in code_paths},
        "dependency_versions": {
            name: importlib.metadata.version(name)
            for name in ("pyarrow", "PyYAML", "pytest", "ruff")
        },
        "counts": counts,
        "random_seed": configuration.get("reproducibility", {}).get("random_seed"),
        "processing_version": "step08-working-v1",
        "runtime_seconds": None,
        "limitations": limitations,
        "checksum_note": "Gzip checksums do not verify decompressed JSONL files.",
    }
    with path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return manifest
