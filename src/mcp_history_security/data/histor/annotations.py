"""Link annotation availability only where source timestamps support it."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .sources import jsonl_records


def extras_events(
    path: Path,
) -> dict[tuple[str, str], set[tuple[str | None, str | None]]]:
    """Retain all extras changes at a server/time so ambiguity remains visible."""
    events: dict[tuple[str, str], set[tuple[str | None, str | None]]] = defaultdict(set)
    for record in jsonl_records(path):
        events[(record["serverId"], record["observedAt"])].add(
            (record["fromExtrasDigest"], record["toExtrasDigest"])
        )
    return dict(events)


def annotation_status(extras: dict, tool: str) -> str:
    """Distinguish unavailable, absent, null, empty and populated annotations."""
    tools = extras.get("tools")
    if not isinstance(tools, dict):
        raise ValueError("extras tools must be an object")
    if tool not in tools:
        return "absent"
    values = tools[tool]
    if not isinstance(values, dict):
        raise ValueError("tool extras must be an object")
    if "annotations" not in values:
        return "absent"
    annotation = values["annotations"]
    if annotation is None:
        return "null"
    if not isinstance(annotation, dict):
        return "malformed"
    if annotation == {}:
        return "empty"
    return "present"


def annotation_fingerprint(extras: dict, tool: str) -> str | None:
    """Fingerprint a known annotation value without retaining its contents."""
    status = annotation_status(extras, tool)
    if status == "malformed":
        return None
    # Include status in the hash so absent, null and empty values cannot be
    # mistaken for one another during before/after comparison.
    value = None if status == "absent" else extras["tools"][tool]["annotations"]
    canonical = json.dumps(
        {"status": status, "value": value},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def annotation_transition(before: str | None, after: str | None) -> str:
    """Compare known values; absent or unresolved evidence is not a negative."""
    if before is None or after is None:
        return "unknown"
    return "unchanged" if before == after else "changed"


def summarize_target_annotation_changes(
    assessments_path: Path, coverage_path: Path, extras_path: Path, output_path: Path
) -> dict:
    """Count value changes for structurally eligible target pairs with linkage."""
    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite annotation summary: {output_path}"
        )
    targets = {}
    columns = [
        "server_id",
        "tool_name",
        "source_type",
        "target_change_id",
        "max_eligible_k",
    ]
    for batch in pq.ParquetFile(assessments_path).iter_batches(columns=columns):
        for row in batch.to_pylist():
            if row["max_eligible_k"] >= 2:
                key = (row["server_id"], row["tool_name"], row["target_change_id"])
                if key in targets:
                    raise ValueError("duplicate eligible target identity")
                targets[key] = {"source_type": row["source_type"]}
    needed: dict[str, set[str]] = defaultdict(set)
    # The coverage file includes all selected states. Restrict comparisons to
    # the actual target event, rather than counting earlier context as updates.
    for batch in pq.ParquetFile(coverage_path).iter_batches():
        for row in batch.to_pylist():
            key = (row["server_id"], row["tool_name"], row["change_id"])
            if key not in targets:
                continue
            side = row["side"]
            if side not in {"before", "after"} or side in targets[key]:
                raise ValueError("duplicate or invalid annotation target state")
            status, digest = row["annotation_status"], row["extras_digest"]
            targets[key][side] = (status, digest)
            if status in {"present", "empty", "null"} and digest:
                needed[digest].add(row["tool_name"])
    values = {}
    for record in jsonl_records(extras_path):
        digest = record["digest"]
        if digest not in needed:
            continue
        try:
            extras = json.loads(record["extrasJson"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid extras record {digest!r}") from exc
        for tool in needed[digest]:
            key = (digest, tool)
            if key in values:
                raise ValueError(f"duplicate extras digest {digest!r}")
            values[key] = (
                annotation_status(extras, tool),
                annotation_fingerprint(extras, tool),
            )
    absent = annotation_fingerprint({"tools": {}}, "unused")
    counts: dict[str, Counter] = defaultdict(Counter)
    for (_, name, _), target in targets.items():
        if "before" not in target or "after" not in target:
            raise ValueError("eligible target lacks an annotation coverage state")
        fingerprints = []
        for side in ("before", "after"):
            status, digest = target.get(side, ("unknown", None))
            if status == "absent":
                fingerprints.append(absent)
            elif status in {"present", "empty", "null"}:
                resolved = values.get((digest, name))
                if resolved is None or resolved[0] != status:
                    raise ValueError("annotation coverage disagrees with extras source")
                fingerprints.append(resolved[1])
            else:
                fingerprints.append(None)
        result = annotation_transition(*fingerprints)
        counts["all"][result] += 1
        counts[target["source_type"]][result] += 1
    summary = {
        "population": "structurally eligible k2 target transitions",
        "method": "exact-time extras linkage; known annotation values compared by hash",
        "counts": {
            source: dict(sorted(values.items()))
            for source, values in sorted(counts.items())
        },
    }
    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return summary


def extract_annotation_statuses(
    path: Path, needed: dict[str, set[str]]
) -> dict[tuple[str, str], str]:
    """Scan extras once for requested digest/name pairs, without retaining tool text."""
    result = {}
    for record in jsonl_records(path):
        digest = record["digest"]
        if digest not in needed:
            continue
        if not isinstance(record.get("extrasJson"), str):
            raise ValueError(f"{path}: invalid extrasJson for {digest!r}")
        try:
            extras = json.loads(record["extrasJson"])
            if not isinstance(extras, dict):
                raise ValueError("extras is not an object")
            for name in needed[digest]:
                key = (digest, name)
                if key in result:
                    raise ValueError(f"duplicate extras digest {digest!r}")
                result[key] = annotation_status(extras, name)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"{path}: invalid extras {digest!r}: {exc}") from exc
    return result


def write_annotation_coverage(
    assessments_path: Path,
    changes_path: Path,
    extras_changes_path: Path,
    extras_path: Path,
    output_path: Path,
) -> dict[str, int]:
    """Link selected states only when a same-time extras change is recorded."""
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite annotation output: {output_path}")
    events = extras_events(extras_changes_path)
    change_times = {
        record["id"]: (record["serverId"], record["observedAt"])
        for record in jsonl_records(changes_path)
    }
    needed: dict[str, set[str]] = defaultdict(set)
    states = []
    for batch in pq.ParquetFile(assessments_path).iter_batches(
        columns=["server_id", "tool_name", "max_eligible_k", "windows_json"]
    ):
        for record in batch.to_pylist():
            length = record["max_eligible_k"]
            if length < 2:
                continue
            selected = json.loads(record["windows_json"])[str(length)]["states"]
            for state in selected:
                key = change_times.get(state["change_id"])
                if key is None or key[0] != record["server_id"]:
                    raise ValueError(
                        "selected state has unresolvable change provenance"
                    )
                # Exact server/time linkage is required: multiple possible
                # extras transitions do not establish which annotation applies.
                choices = events.get(key, set())
                digest = None
                if len(choices) == 1:
                    pair = next(iter(choices))
                    digest = pair[0 if state["side"] == "before" else 1]
                if digest:
                    needed[digest].add(record["tool_name"])
                states.append(
                    {
                        "server_id": record["server_id"],
                        "tool_name": record["tool_name"],
                        "change_id": state["change_id"],
                        "side": state["side"],
                        "extras_digest": digest,
                    }
                )
    statuses = extract_annotation_statuses(extras_path, dict(needed))
    unknown = 0
    for state in states:
        digest = state["extras_digest"]
        # Missing linkage is unknown; the source's empty digest is a distinct
        # explicit absence and must not be treated as an unresolved reference.
        if digest is None:
            state["annotation_status"] = "unknown"
        elif digest == "":
            state["annotation_status"] = "absent"
        else:
            state["annotation_status"] = statuses.get(
                (digest, state["tool_name"]), "unresolved_reference"
            )
        unknown += state["annotation_status"] in {"unknown", "unresolved_reference"}
    schema = pa.schema(
        [
            ("server_id", pa.string()),
            ("tool_name", pa.string()),
            ("change_id", pa.int64()),
            ("side", pa.string()),
            ("extras_digest", pa.string()),
            ("annotation_status", pa.string()),
        ]
    )
    pq.write_table(
        pa.Table.from_pylist(states, schema=schema), output_path, compression="zstd"
    )
    return {"selected_states": len(states), "unknown_or_unresolved": unknown}
