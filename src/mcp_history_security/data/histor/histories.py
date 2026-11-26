"""Reconstruct recorded per-tool histories from changes and definition index."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .index import DefinitionStore
from .revisions import revision_kind
from .sources import jsonl_records, sha256_file


def load_server_changes(
    path: Path,
) -> tuple[dict[str, list[dict]], dict[str, set[str]]]:
    """Read server events and exact modified-tool identities from source changes."""
    events: dict[str, list[dict]] = defaultdict(list)
    candidates: dict[str, set[str]] = defaultdict(set)
    for record in jsonl_records(path):
        try:
            summary = json.loads(record["summaryJson"])
            modified = summary.get("modified", [])
            if not isinstance(modified, list):
                raise ValueError("modified must be a list")
            names = [item["tool"] for item in modified]
            if any(not isinstance(name, str) for name in names):
                raise ValueError("modified tool names must be strings")
            server_id = record["serverId"]
            # Only explicitly modified tools enter the population; keep all
            # server events so intervening gaps remain visible in their history.
            candidates[server_id].update(names)
            events[server_id].append(
                {
                    "id": record["id"],
                    "time": record["observedAt"],
                    "before": record["fromToolSetDigest"],
                    "after": record["toToolSetDigest"],
                    "detail": summary.get("detail", "unknown"),
                    "modified": names,
                }
            )
        except (
            KeyError,
            TypeError,
            AttributeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError(
                f"{path}: invalid change {record.get('id')!r}: {exc}"
            ) from exc
    for server_events in events.values():
        server_events.sort(key=lambda event: (event["time"], event["id"]))
    return dict(events), dict(candidates)


def reconstruct_histories(
    changes_path: Path, index_path: Path, cache_bytes: int = 67108864
) -> Iterator[dict]:
    """Yield histories in stable identity order; never modify the definition index."""
    events, candidates = load_server_changes(changes_path)
    with DefinitionStore(
        index_path, changes_path.parent / "toolsets.jsonl", cache_bytes
    ) as store:
        if sha256_file(changes_path) != store.changes_sha256:
            raise ValueError(f"source checksum does not match index: {changes_path}")

        @lru_cache(maxsize=50000)
        def definition(
            digest: str | None, name: str
        ) -> tuple[str, str | None, dict | None]:
            return store.lookup(digest, name)

        @lru_cache(maxsize=50000)
        def reference(
            digest: str | None, name: str
        ) -> tuple[str, str | None, int | None]:
            return store.reference(digest, name)

        for server_id in sorted(candidates):
            server_events = events[server_id]
            for name in sorted(candidates[server_id]):
                history = []
                for pos, event in enumerate(server_events):
                    before_status, before_hash, _ = reference(event["before"], name)
                    after_status, after_hash, _ = reference(event["after"], name)
                    issues = []
                    if pos and server_events[pos - 1]["after"] != event["before"]:
                        issues.append("server_chain_break_before")
                    # Sorting by ID is deterministic, but it does not establish
                    # the true order of observations with identical timestamps.
                    if (pos and server_events[pos - 1]["time"] == event["time"]) or (
                        pos + 1 < len(server_events)
                        and server_events[pos + 1]["time"] == event["time"]
                    ):
                        issues.append("same_timestamp_ambiguity")
                    if event["detail"] == "names-only":
                        issues.append("names_only")
                    if before_status != "present" or after_status != "present":
                        issues.append("unresolved_state")
                    modified = name in event["modified"]
                    if before_status == "present" and after_status == "present":
                        # Verified indexed hashes avoid parsing large toolsets
                        # when this tool's definition did not change.
                        if before_hash == after_hash:
                            kind = "unchanged"
                        else:
                            _, _, before = definition(event["before"], name)
                            _, _, after = definition(event["after"], name)
                            if before is None or after is None:
                                raise ValueError(
                                    "indexed definition unexpectedly unavailable"
                                )
                            kind = revision_kind(before, after, same_content=False)
                        # Keep disagreements between the summary and actual
                        # definitions explicit rather than choosing one source.
                        if (kind == "unchanged") == modified:
                            issues.append("summary_definition_mismatch")
                    else:
                        kind = "unknown"
                    history.append(
                        {
                            "change_id": event["id"],
                            "observed_at": event["time"],
                            "before_digest": event["before"],
                            "after_digest": event["after"],
                            "before_status": before_status,
                            "after_status": after_status,
                            "before_hash": before_hash,
                            "after_hash": after_hash,
                            "recorded_modification": modified,
                            "revision_kind": kind,
                            "issues": issues,
                        }
                    )
                yield {"server_id": server_id, "tool_name": name, "events": history}


def write_histories(
    changes_path: Path, index_path: Path, output: Path, cache_bytes: int = 67108864
) -> dict[str, int]:
    """Write a new history artifact without claiming completion on interruption."""
    if output.exists():
        raise FileExistsError(f"refusing to overwrite history output: {output}")
    schema = pa.schema(
        [
            ("server_id", pa.string()),
            ("tool_name", pa.string()),
            ("events_json", pa.large_string()),
        ]
    )
    count = 0
    events = 0
    batch: list[dict] = []
    with pq.ParquetWriter(output, schema, compression="zstd") as writer:
        for history in reconstruct_histories(changes_path, index_path, cache_bytes):
            count += 1
            events += len(history["events"])
            batch.append(
                {
                    "server_id": history["server_id"],
                    "tool_name": history["tool_name"],
                    "events_json": json.dumps(history["events"], ensure_ascii=False),
                }
            )
            if len(batch) == 1000:
                writer.write_table(pa.Table.from_pylist(batch, schema=schema))
                batch.clear()
        if batch:
            writer.write_table(pa.Table.from_pylist(batch, schema=schema))
    return {"histories": count, "server_transition_entries": events}
