"""Preserve availability of HISTOR advisory classifications without labeling."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .sources import jsonl_records


def load_classifications(path: Path) -> dict[str, list[dict]]:
    """Collect model and finding-count metadata by toolset digest."""
    result: dict[str, list[dict]] = defaultdict(list)
    for record in jsonl_records(path):
        verdict = json.loads(record["verdictJson"])
        if not isinstance(verdict, dict) or not isinstance(
            verdict.get("findings"), list
        ):
            raise ValueError(f"{path}: malformed classification verdict")
        result[record["toolSetDigest"]].append(
            {
                "model": record.get("model"),
                "updated_at": record.get("updatedAt"),
                "finding_count": len(verdict["findings"]),
                "checked_tools": verdict.get("checkedTools"),
                "tool_count": verdict.get("toolCount"),
                "truncated_tools": verdict.get("truncatedTools"),
            }
        )
    return dict(result)


def write_classification_coverage(
    assessments_path: Path, classifications_path: Path, output_path: Path
) -> dict[str, int]:
    """Store availability for selected states; absent classifications are unknown."""
    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite classification output: {output_path}"
        )
    classifications = load_classifications(classifications_path)
    schema = pa.schema(
        [
            ("server_id", pa.string()),
            ("tool_name", pa.string()),
            ("change_id", pa.int64()),
            ("side", pa.string()),
            ("toolset_digest", pa.string()),
            ("coverage", pa.string()),
            ("classification_metadata_json", pa.string()),
        ]
    )
    count = 0
    present = 0
    pending = []
    with pq.ParquetWriter(output_path, schema, compression="zstd") as writer:
        for batch in pq.ParquetFile(assessments_path).iter_batches(
            columns=["server_id", "tool_name", "max_eligible_k", "windows_json"]
        ):
            for row in batch.to_pylist():
                k = row["max_eligible_k"]
                if k < 2:
                    continue
                for state in json.loads(row["windows_json"])[str(k)]["states"]:
                    entries = classifications.get(state["toolset_digest"])
                    if entries is None:
                        coverage = "unavailable"
                    elif any(
                        entry["truncated_tools"] == 0
                        and isinstance(entry["checked_tools"], int)
                        and isinstance(entry["tool_count"], int)
                        and entry["checked_tools"] >= entry["tool_count"]
                        for entry in entries
                    ):
                        coverage = "available_full_toolset"
                    else:
                        coverage = "available_partial_or_unknown"
                    pending.append(
                        {
                            "server_id": row["server_id"],
                            "tool_name": row["tool_name"],
                            "change_id": state["change_id"],
                            "side": state["side"],
                            "toolset_digest": state["toolset_digest"],
                            "coverage": coverage,
                            "classification_metadata_json": json.dumps(
                                entries, sort_keys=True
                            )
                            if entries is not None
                            else None,
                        }
                    )
                    count += 1
                    present += entries is not None
                    if len(pending) == 1000:
                        writer.write_table(pa.Table.from_pylist(pending, schema=schema))
                        pending.clear()
        if pending:
            writer.write_table(pa.Table.from_pylist(pending, schema=schema))
    return {"selected_states": count, "classification_available": present}
