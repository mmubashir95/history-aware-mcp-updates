"""Parse individual-tool modification events from HISTOR change records."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .sources import jsonl_records


@dataclass(frozen=True)
class Modification:
    """A recorded modification, retaining its source change and digest links."""

    server_id: str
    tool_name: str
    change_id: int
    observed_at: str
    before_digest: str | None
    after_digest: str | None
    detail: str
    fields_json: str


def modifications(path: Path) -> Iterator[Modification]:
    """Yield only explicitly recorded modifications, not additions or removals."""
    for record in jsonl_records(path):
        try:
            summary = json.loads(record["summaryJson"])
            if not isinstance(summary, dict):
                raise ValueError("summary is not an object")
            modified = summary.get("modified", [])
            if not isinstance(modified, list):
                raise ValueError("modified is not a list")
            for item in modified:
                if not isinstance(item, dict) or not isinstance(item.get("tool"), str):
                    raise ValueError("modified item has no string tool name")
                fields = item.get("fields", {})
                if not isinstance(fields, dict):
                    raise ValueError("modified fields is not an object")
                yield Modification(
                    server_id=record["serverId"],
                    tool_name=item["tool"],
                    change_id=record["id"],
                    observed_at=record["observedAt"],
                    before_digest=record["fromToolSetDigest"],
                    after_digest=record["toToolSetDigest"],
                    detail=summary.get("detail", "unknown"),
                    fields_json=json.dumps(fields, ensure_ascii=False, sort_keys=True),
                )
        except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(
                f"{path}: invalid change {record.get('id')!r}: {exc}"
            ) from exc


def change_version_metadata(path: Path) -> dict[int, dict]:
    """Retain recorded package, server and registry versions with missingness."""
    fields = (
        "fromPackageVersion",
        "toPackageVersion",
        "fromServerVersion",
        "toServerVersion",
        "fromRegistryVersion",
        "toRegistryVersion",
    )
    versions = {}
    for record in jsonl_records(path):
        identifier = record["id"]
        if identifier in versions:
            raise ValueError(f"{path}: duplicate change id {identifier!r}")
        values = {}
        for field in fields:
            if field in record:
                value = record[field]
                if value is not None and not isinstance(value, str):
                    raise ValueError(
                        f"{path}: invalid {field} in change {identifier!r}"
                    )
                values[field] = value
        versions[identifier] = values
    return versions
