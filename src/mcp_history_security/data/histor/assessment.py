"""Assess reconstructed histories without using scanner results as eligibility."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .metadata import annotate_launch_evidence
from .scanner import compare_findings
from .windows import assess_windows


def assess_history(history: dict, metadata: dict, launches: dict, scans: dict) -> dict:
    """Return structural decisions and independent metadata for one candidate."""
    source_type = metadata.get("source_type", "unknown")
    annotate_launch_evidence(history, source_type, launches)
    events = history["events"]
    max_supported = max(
        20, 2 * sum(event["recorded_modification"] for event in events) + 2
    )
    result = assess_windows(history, max_supported)
    windows = result["windows"]
    eligible_lengths = [int(k) for k, value in windows.items() if value["eligible"]]
    max_eligible = max(eligible_lengths, default=0)
    target = next(
        (event for event in events if event["change_id"] == result["target_change_id"]),
        None,
    )
    target_index = events.index(target) if target is not None else -1
    ordered_hashes = []
    has_unknown = False
    for event in events[: target_index + 1]:
        for key in ("before_hash", "after_hash"):
            value = event[key]
            if value is None:
                has_unknown = True
                value = "unknown"
            if not ordered_hashes or ordered_hashes[-1] != value:
                ordered_hashes.append(value)
    # Unknown states cannot be asserted equal across tools.
    signature = {"states": ordered_hashes}
    if has_unknown or target is None:
        signature["unresolved_identity"] = [history["server_id"], history["tool_name"]]
    cluster_id = hashlib.sha256(
        json.dumps(signature, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    quality = Counter(issue for event in events for issue in event["issues"])
    kinds = Counter(
        event["revision_kind"] for event in events if event["recorded_modification"]
    )
    if target:
        scanner = compare_findings(
            scans, target["before_digest"], target["after_digest"], history["tool_name"]
        )
        launch_status = target.get("launch_compatibility", "unknown")
    else:
        scanner = {"coverage": "no_target"}
        launch_status = "unknown"
    return {
        "server_id": history["server_id"],
        "tool_name": history["tool_name"],
        "source_type": source_type,
        "server_name": metadata.get("server_name"),
        "publisher_name_prefix": metadata.get("publisher_name_prefix"),
        "repository": metadata.get("repository"),
        "package_identity": metadata.get("package_identity"),
        "delisted": metadata.get("delisted"),
        "target_change_id": result["target_change_id"],
        "target_timestamp": target["observed_at"] if target else None,
        "latest_observation_timestamp": events[-1]["observed_at"] if events else None,
        "max_eligible_k": max_eligible,
        "windows_json": json.dumps(windows, sort_keys=True, separators=(",", ":")),
        "cluster_id": cluster_id,
        "quality_json": json.dumps(dict(quality), sort_keys=True),
        "revision_counts_json": json.dumps(dict(kinds), sort_keys=True),
        "target_scanner_json": json.dumps(scanner, sort_keys=True),
        "target_launch_compatibility": launch_status,
        "target_before_launch_signature": target.get("before_launch_signature")
        if target
        else None,
        "target_after_launch_signature": target.get("after_launch_signature")
        if target
        else None,
        "annotation_coverage": "unknown",
    }


def assessed_rows(history_path: Path, metadata: dict, launches: dict, scans: dict):
    """Stream one assessment for each reconstructed tool identity."""
    file = pq.ParquetFile(history_path)
    for batch in file.iter_batches(batch_size=1000):
        for record in batch.to_pylist():
            history = {
                "server_id": record["server_id"],
                "tool_name": record["tool_name"],
                "events": json.loads(record["events_json"]),
            }
            yield assess_history(
                history, metadata.get(record["server_id"], {}), launches, scans
            )


def write_assessments(
    history_path: Path, output: Path, metadata: dict, launches: dict, scans: dict
) -> int:
    """Write preliminary assessments to a new Parquet file."""
    if output.exists():
        raise FileExistsError(f"refusing to overwrite assessment output: {output}")
    schema = pa.schema(
        [
            ("server_id", pa.string()),
            ("tool_name", pa.string()),
            ("source_type", pa.string()),
            ("server_name", pa.string()),
            ("publisher_name_prefix", pa.string()),
            ("repository", pa.string()),
            ("package_identity", pa.string()),
            ("delisted", pa.bool_()),
            ("target_change_id", pa.int64()),
            ("target_timestamp", pa.string()),
            ("latest_observation_timestamp", pa.string()),
            ("max_eligible_k", pa.int32()),
            ("windows_json", pa.large_string()),
            ("cluster_id", pa.string()),
            ("quality_json", pa.string()),
            ("revision_counts_json", pa.string()),
            ("target_scanner_json", pa.string()),
            ("target_launch_compatibility", pa.string()),
            ("target_before_launch_signature", pa.string()),
            ("target_after_launch_signature", pa.string()),
            ("annotation_coverage", pa.string()),
        ]
    )
    rows = []
    count = 0
    with pq.ParquetWriter(output, schema, compression="zstd") as writer:
        for row in assessed_rows(history_path, metadata, launches, scans):
            rows.append(row)
            count += 1
            if len(rows) == 1000:
                writer.write_table(pa.Table.from_pylist(rows, schema=schema))
                rows.clear()
        if rows:
            writer.write_table(pa.Table.from_pylist(rows, schema=schema))
    return count
