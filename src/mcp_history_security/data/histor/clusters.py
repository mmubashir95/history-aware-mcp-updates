"""Group histories conservatively by shared selected definitions or templates."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .index import DefinitionStore
from .revisions import hidden_characters

_COUNTER = re.compile(r"\b\d+(?=\s+tools\b)", re.IGNORECASE)
_DIGITS = re.compile(r"\d+")


def build_clusters(
    assessments_path: Path,
    index_path: Path,
    toolsets_path: Path,
    output_path: Path,
    cache_bytes: int = 67108864,
) -> dict:
    """Group any histories sharing a state or recognized counter template.

    This is a conservative leakage grouping, not evidence of statistical
    independence. Histories without an eligible window remain unresolved.
    """
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite clusters: {output_path}")
    table = pq.read_table(
        assessments_path,
        columns=[
            "server_id",
            "tool_name",
            "windows_json",
            "max_eligible_k",
            "cluster_id",
        ],
    )
    records = table.to_pylist()
    parent = list(range(len(records)))
    owners: dict[str, int] = {}
    edge_types: list[set[str]] = [set() for _ in records]

    def root(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    # Shared states and templates form transitive leakage groups: if A links
    # to B and B links to C, all three must be kept together during splitting.
    def union(left: int, right: int) -> None:
        left, right = root(left), root(right)
        if left != right:
            parent[max(left, right)] = min(left, right)

    with DefinitionStore(index_path, toolsets_path, cache_bytes) as store:

        @lru_cache(maxsize=50000)
        def templates(
            digest: str, name: str, expected_hash: str
        ) -> tuple[str | None, str | None]:
            status, actual_hash, tool = store.lookup(digest, name)
            if status != "present" or actual_hash != expected_hash or tool is None:
                raise ValueError(f"unresolvable definition reference {digest!r}")
            value = dict(tool)
            description = value.get("description")
            signatures = []
            # Numeric normalization is a grouping heuristic only. It can
            # over-group unrelated definitions and never makes an edit trivial.
            for pattern, placeholder in (
                (_COUNTER, "<tool-count>"),
                (_DIGITS, "<number>"),
            ):
                if not isinstance(description, str) or hidden_characters(description):
                    signatures.append(None)
                    continue
                value["description"] = pattern.sub(placeholder, description)
                if value["description"] == description:
                    signatures.append(None)
                    continue
                encoded = json.dumps(
                    value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                )
                signatures.append(hashlib.sha256(encoded.encode("utf-8")).hexdigest())
            return signatures[0], signatures[1]

        for index, record in enumerate(records):
            k = record["max_eligible_k"]
            if k < 2:
                continue
            states = json.loads(record["windows_json"])[str(k)]["states"]
            for state in states:
                digest, definition_hash = (
                    state["toolset_digest"],
                    state["definition_hash"],
                )
                counter_template, numeric_template = templates(
                    digest, record["tool_name"], definition_hash
                )
                for kind, signature in (
                    ("shared_definition", definition_hash),
                    ("counter_template", counter_template),
                    ("numeric_description_template", numeric_template),
                ):
                    if signature is None:
                        continue
                    token = kind + ":" + signature
                    if token in owners:
                        other = owners[token]
                        if other != index:
                            union(index, other)
                            edge_types[index].add(kind)
                            edge_types[other].add(kind)
                    else:
                        owners[token] = index

    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(records)):
        groups[root(index)].append(index)
    result = []
    for members in groups.values():
        # Hash the sorted member identities so cluster IDs do not depend on
        # traversal order or on the union-find root chosen above.
        identities = sorted(
            (records[i]["server_id"], records[i]["tool_name"]) for i in members
        )
        cluster_id = hashlib.sha256(
            json.dumps(identities, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        kinds = sorted({kind for i in members for kind in edge_types[i]})
        for index in members:
            record = records[index]
            result.append(
                {
                    "server_id": record["server_id"],
                    "tool_name": record["tool_name"],
                    "cluster_id": cluster_id,
                    "exact_history_signature": record["cluster_id"],
                    "cluster_size": len(members),
                    "matching_methods": kinds,
                    "representative": (record["server_id"], record["tool_name"])
                    == identities[0],
                    "evidence_status": "selected_states"
                    if record["max_eligible_k"] >= 2
                    else "unresolved",
                }
            )
    pq.write_table(pa.Table.from_pylist(result), output_path, compression="zstd")
    return {
        "histories": len(records),
        "clusters": len(groups),
        "multi_member_clusters": sum(len(x) > 1 for x in groups.values()),
    }
