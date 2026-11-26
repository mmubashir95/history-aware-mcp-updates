"""Source and launch-configuration evidence for observed histories."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

from .sources import jsonl_records


def server_metadata(path: Path) -> dict[str, dict]:
    """Read source metadata; publisher is an explicitly marked name-prefix proxy."""
    result = {}
    for record in jsonl_records(path):
        server_id = record["id"]
        if server_id in result:
            raise ValueError(f"{path}: duplicate server id {server_id!r}")
        # This is current endpoint metadata, not proof that the server used
        # the same source type for every historical observation.
        endpoint = record.get("endpoint")
        if isinstance(endpoint, str) and endpoint.startswith("npm:"):
            source_type = "npm"
        elif isinstance(endpoint, str) and endpoint.startswith("pypi:"):
            source_type = "pypi"
        elif isinstance(endpoint, str) and endpoint.startswith(("https://", "http://")):
            source_type = "remote"
        else:
            source_type = "unknown"
        name = record.get("name")
        result[server_id] = {
            "source_type": source_type,
            "server_name": name,
            "publisher_name_prefix": name.split("/", 1)[0]
            if isinstance(name, str) and "/" in name
            else None,
            "repository": record.get("repository"),
            "delisted": record.get("delisted"),
            "package_identity": endpoint if source_type in {"npm", "pypi"} else None,
        }
    return result


def launch_evidence(path: Path) -> dict[tuple[str, str], set[str | None]]:
    """Group launch configurations observed for each server and toolset digest."""
    result: dict[tuple[str, str], set[str | None]] = defaultdict(set)
    for record in jsonl_records(path):
        digest = record.get("toolSetDigest")
        if not digest:
            continue
        raw = record.get("launchJson")
        if raw is None:
            signature = None
        else:
            try:
                value = json.loads(raw)
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"{path}: invalid launchJson at observation {record.get('id')}"
                ) from exc
            canonical = json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            signature = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        result[(record["serverId"], digest)].add(signature)
    return dict(result)


def launch_compatibility(before: set[str | None], after: set[str | None]) -> str:
    """Return known compatibility only for unambiguous recorded configurations."""
    # Missing or multiple observed launch settings cannot establish that two
    # package observations were produced by compatible configurations.
    if len(before) != 1 or len(after) != 1 or None in before or None in after:
        return "unknown"
    return "matching" if before == after else "different"


def annotate_launch_evidence(
    history: dict, source_type: str, evidence: dict[tuple[str, str], set[str | None]]
) -> None:
    """Mark package transitions without inferring missing launch settings."""
    for event in history["events"]:
        if source_type not in {"npm", "pypi"}:
            event["launch_compatibility"] = (
                "not_applicable" if source_type == "remote" else "unknown"
            )
            continue
        before = evidence.get((history["server_id"], event["before_digest"]), set())
        after = evidence.get((history["server_id"], event["after_digest"]), set())
        status = launch_compatibility(before, after)
        event["launch_compatibility"] = status
        event["before_launch_signature"] = (
            next(iter(before)) if len(before) == 1 else None
        )
        event["after_launch_signature"] = next(iter(after)) if len(after) == 1 else None
        if status == "different":
            event["issues"].append("launch_configuration_changed")
