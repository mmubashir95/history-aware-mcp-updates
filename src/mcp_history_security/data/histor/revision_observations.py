"""Measure narrow textual change patterns without deciding their significance."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq

from .sources import definition_hash, jsonl_records

_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _fingerprint(tool: dict) -> tuple[bytes, bytes, bytes, bytes, bool] | None:
    description = tool.get("description")
    if not isinstance(description, str):
        return None

    def digest(value: str) -> bytes:
        return hashlib.sha256(value.encode("utf-8")).digest()

    # Tuple positions hold hashes of: non-description fields, original text,
    # text without whitespace, text with ISO dates masked, and date presence.
    # These are comparison fingerprints; they do not classify edits as benign.
    return (
        bytes.fromhex(
            definition_hash({k: v for k, v in tool.items() if k != "description"})
        ),
        digest(description),
        digest("".join(description.split())),
        digest(_DATE.sub("<date>", description)),
        bool(_DATE.search(description)),
    )


def _compare_patterns(
    old: tuple[bytes, bytes, bytes, bytes, bool] | None,
    new: tuple[bytes, bytes, bytes, bytes, bool] | None,
) -> set[str]:
    if old is None or new is None:
        return {"description_unavailable"}
    result = set()
    if old[0] == new[0] and old[1] != new[1]:
        if old[2] == new[2]:
            result.add("whitespace_only_candidate")
        if old[4] and new[4] and old[3] == new[3]:
            result.add("iso_date_only_candidate")
    return result


def text_patterns(before: dict, after: dict) -> set[str]:
    """Return mechanical pattern candidates; none are classified as trivial."""
    return _compare_patterns(_fingerprint(before), _fingerprint(after))


def summarize_text_patterns(
    history_path: Path, toolsets_path: Path, output: Path
) -> dict:
    """Stream source toolsets once and count observed description-only patterns.

    Fingerprints are retained in memory, but original definitions and text are
    not written to the output. Both sides must resolve to their recorded hashes.
    """
    if output.exists():
        raise FileExistsError(f"refusing to overwrite revision summary: {output}")
    # Collect references first so each source toolset is parsed at most once
    # during the scan and original tool text is never written to the output.
    wanted: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    transitions = []
    total = 0
    unresolved = 0
    for batch in pq.ParquetFile(history_path).iter_batches(batch_size=1000):
        for row in batch.to_pylist():
            name = row["tool_name"]
            for event in json.loads(row["events_json"]):
                if not event["recorded_modification"]:
                    continue
                total += 1
                if (
                    event["before_status"] != "present"
                    or event["after_status"] != "present"
                ):
                    unresolved += 1
                    continue
                before = (event["before_digest"], name, event["before_hash"])
                after = (event["after_digest"], name, event["after_hash"])
                for digest, tool_name, definition in (before, after):
                    wanted[digest][tool_name].add(definition)
                transitions.append((before, after))
    fingerprints = {}
    seen_digests = set()
    for record in jsonl_records(toolsets_path):
        digest = record["digest"]
        if digest not in wanted:
            continue
        if digest in seen_digests:
            raise ValueError(f"duplicate toolset digest {digest!r}")
        seen_digests.add(digest)
        tools = json.loads(record["toolsJson"])
        if isinstance(tools, dict):
            tools = tools.get("tools")
        if not isinstance(tools, list):
            raise ValueError(f"invalid toolsJson for digest {digest!r}")
        for tool in tools:
            if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                raise ValueError(f"invalid tool in digest {digest!r}")
            name = tool["name"]
            if name not in wanted[digest]:
                continue
            content_hash = definition_hash(tool)
            # Match the recorded full-content hash, not just a potentially
            # repeated tool name within the source toolset.
            if content_hash in wanted[digest][name]:
                fingerprints[(digest, name, content_hash)] = _fingerprint(tool)
    counts: Counter = Counter()
    for before, after in transitions:
        if before not in fingerprints or after not in fingerprints:
            raise ValueError(
                "recorded definition reference missing from source toolsets"
            )
        counts.update(_compare_patterns(fingerprints[before], fingerprints[after]))
    result = {
        "population": "recorded modified-tool events",
        "recorded_modifications": total,
        "unresolved_events": unresolved,
        "resolved_events": len(transitions),
        "counts": dict(sorted(counts.items())),
        "limitations": (
            "Description-only mechanical candidates; not triviality or security "
            "labels. ISO YYYY-MM-DD patterns only; categories may overlap."
        ),
    }
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return result
