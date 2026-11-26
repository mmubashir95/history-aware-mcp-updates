"""Measure field availability on selected, indexed definition references."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .index import DefinitionStore
from .revisions import hidden_characters


def field_status(definition: dict, key: str) -> str:
    """Preserve the distinction among absent, null, empty, and present fields."""
    if key not in definition:
        return "absent"
    value = definition[key]
    if value is None:
        return "null"
    if value == "" or value == {} or value == []:
        return "empty"
    return "present"


def definition_hidden(value: object) -> bool:
    """Find hidden Unicode in keys and string values without logging tool text."""
    if isinstance(value, str):
        return hidden_characters(value)
    if isinstance(value, list):
        return any(definition_hidden(item) for item in value)
    if isinstance(value, dict):
        return any(
            definition_hidden(key) or definition_hidden(item)
            for key, item in value.items()
        )
    return False


def write_field_coverage(
    assessments_path: Path,
    index_path: Path,
    toolsets_path: Path,
    output_path: Path,
    cache_bytes: int = 67108864,
) -> dict[str, int]:
    """Store availability per selected state and retain its source references."""
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite field coverage: {output_path}")
    schema = pa.schema(
        [
            ("server_id", pa.string()),
            ("tool_name", pa.string()),
            ("change_id", pa.int64()),
            ("side", pa.string()),
            ("toolset_digest", pa.string()),
            ("description", pa.string()),
            ("input_schema", pa.string()),
            ("output_schema", pa.string()),
            ("hidden_characters", pa.bool_()),
        ]
    )
    pending = []
    count = 0
    with DefinitionStore(index_path, toolsets_path, cache_bytes) as store:

        @lru_cache(maxsize=50000)
        def lookup(digest: str, name: str, expected_hash: str) -> dict:
            status, actual_hash, tool = store.lookup(digest, name)
            if status != "present" or actual_hash != expected_hash or tool is None:
                raise ValueError(f"unresolvable selected state {digest!r}")
            return tool

        with pq.ParquetWriter(output_path, schema, compression="zstd") as writer:
            for batch in pq.ParquetFile(assessments_path).iter_batches(
                columns=["server_id", "tool_name", "max_eligible_k", "windows_json"]
            ):
                for record in batch.to_pylist():
                    k = record["max_eligible_k"]
                    if k < 2:
                        continue
                    for state in json.loads(record["windows_json"])[str(k)]["states"]:
                        definition = lookup(
                            state["toolset_digest"],
                            record["tool_name"],
                            state["definition_hash"],
                        )
                        pending.append(
                            {
                                "server_id": record["server_id"],
                                "tool_name": record["tool_name"],
                                "change_id": state["change_id"],
                                "side": state["side"],
                                "toolset_digest": state["toolset_digest"],
                                "description": field_status(definition, "description"),
                                "input_schema": field_status(definition, "inputSchema"),
                                "output_schema": field_status(
                                    definition, "outputSchema"
                                ),
                                "hidden_characters": definition_hidden(definition),
                            }
                        )
                        count += 1
                        if len(pending) == 1000:
                            writer.write_table(
                                pa.Table.from_pylist(pending, schema=schema)
                            )
                            pending.clear()
            if pending:
                writer.write_table(pa.Table.from_pylist(pending, schema=schema))
    return {"selected_states": count}
