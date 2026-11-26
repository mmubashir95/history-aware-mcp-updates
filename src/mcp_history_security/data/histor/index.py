"""Build a disk-backed tool-definition index for recorded modified tools."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import OrderedDict, defaultdict
from copy import deepcopy
from pathlib import Path

from .changes import modifications
from .sources import definition_hash, jsonl_records, sha256_file


def needed_definitions(changes_path: Path) -> dict[str, set[str]]:
    """Map observed toolset digests to modified names on their server.

    Include all recorded server transitions, not only transitions where a
    particular tool was modified, so intervening observations remain visible.
    """
    tools: dict[str, set[str]] = defaultdict(set)
    for event in modifications(changes_path):
        tools[event.server_id].add(event.tool_name)
    needed: dict[str, set[str]] = defaultdict(set)
    for record in jsonl_records(changes_path):
        try:
            names = tools.get(record["serverId"], set())
            for key in ("fromToolSetDigest", "toToolSetDigest"):
                digest = record[key]
                if digest is not None and not isinstance(digest, str):
                    raise ValueError(f"{key} must be a string or null")
                if digest:
                    needed[digest].update(names)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{changes_path}: invalid digest linkage: {exc}") from exc
    return dict(needed)


def build_definition_index(
    changes_path: Path, toolsets_path: Path, output: Path
) -> dict:
    """Build an index at a new path, never overwriting an existing index.

    Store source byte offsets and tool ordinals instead of copying tool text.
    Duplicate names are retained as ambiguous, rather than resolved by ordering.
    """
    if output.exists():
        raise FileExistsError(f"refusing to overwrite index: {output}")
    needed = needed_definitions(changes_path)
    found: set[str] = set()
    rows = 0
    with sqlite3.connect(output) as db:
        db.execute(
            "CREATE TABLE definitions (digest TEXT NOT NULL, name TEXT NOT NULL, "
            "definition_hash TEXT NOT NULL, tool_ordinal INTEGER NOT NULL, "
            "occurrences INTEGER NOT NULL, "
            "PRIMARY KEY (digest, name, definition_hash)) WITHOUT ROWID"
        )
        db.execute(
            "CREATE TABLE toolsets (digest TEXT PRIMARY KEY, "
            "byte_offset INTEGER NOT NULL, byte_length INTEGER NOT NULL) WITHOUT ROWID"
        )
        db.execute(
            "CREATE TABLE metadata (key TEXT PRIMARY KEY, "
            "value TEXT NOT NULL) WITHOUT ROWID"
        )
        # Offsets refer to these exact bytes; record their hash while building
        # so a later lookup can reject a changed or different source file.
        source_hash = hashlib.sha256()
        with toolsets_path.open("rb") as stream:
            while True:
                offset = stream.tell()
                line = stream.readline()
                if not line:
                    break
                source_hash.update(line)
                try:
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError("toolset record must be an object")
                    digest = record["digest"]
                    if digest not in needed:
                        continue
                    if digest in found:
                        raise ValueError(f"duplicate toolset digest {digest!r}")
                    found.add(digest)
                    tools = json.loads(record["toolsJson"])
                    if isinstance(tools, dict):
                        tools = tools.get("tools")
                    if not isinstance(tools, list):
                        raise ValueError("toolsJson must contain a list")
                    db.execute(
                        "INSERT INTO toolsets VALUES (?, ?, ?)",
                        (digest, offset, len(line)),
                    )
                    for ordinal, tool in enumerate(tools):
                        if not isinstance(tool, dict) or not isinstance(
                            tool.get("name"), str
                        ):
                            raise ValueError(
                                "tool must be an object with a string name"
                            )
                        if tool["name"] not in needed[digest]:
                            continue
                        db.execute(
                            "INSERT INTO definitions VALUES (?, ?, ?, ?, 1) "
                            "ON CONFLICT(digest, name, definition_hash) DO UPDATE SET "
                            "occurrences = occurrences + 1",
                            (digest, tool["name"], definition_hash(tool), ordinal),
                        )
                        rows += 1
                except (
                    KeyError,
                    TypeError,
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                    ValueError,
                ) as exc:
                    raise ValueError(
                        f"{toolsets_path}: invalid toolset at byte {offset}: {exc}"
                    ) from exc
        db.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            [
                ("schema_version", "2"),
                ("status", "complete"),
                ("toolsets_sha256", source_hash.hexdigest()),
                ("changes_sha256", sha256_file(changes_path)),
            ],
        )
    return {
        "requested_digests": len(needed),
        "found_digests": len(found),
        "missing_digests": len(needed.keys() - found),
        "definition_rows_seen": rows,
    }


class DefinitionStore:
    """Resolve indexed definitions from immutable source offsets on demand."""

    def __init__(
        self, index_path: Path, toolsets_path: Path, cache_bytes: int = 67108864
    ) -> None:
        if type(cache_bytes) is not int or cache_bytes < 0:
            raise ValueError("cache_bytes must be a nonnegative integer")
        self.database = sqlite3.connect(
            index_path.resolve().as_uri() + "?mode=ro", uri=True
        )
        try:
            metadata = dict(self.database.execute("SELECT key, value FROM metadata"))
            if (
                metadata.get("schema_version") != "2"
                or metadata.get("status") != "complete"
            ):
                raise ValueError(
                    f"incomplete or incompatible definition index: {index_path}"
                )
            # A valid SQLite index alone is insufficient: byte offsets and
            # indexed content hashes are only valid for the original source.
            if sha256_file(toolsets_path) != metadata.get("toolsets_sha256"):
                raise ValueError(
                    f"source checksum does not match index: {toolsets_path}"
                )
            self.changes_sha256 = metadata.get("changes_sha256")
            self.stream = toolsets_path.open("rb")
            self.cache_limit_bytes = cache_bytes
            self.cache_bytes = 0
            self.cache: OrderedDict[str, tuple[list, int]] = OrderedDict()
        except sqlite3.Error as exc:
            self.database.close()
            raise ValueError(f"invalid definition index: {index_path}") from exc
        except (OSError, ValueError):
            self.database.close()
            raise

    def _read_toolset(self, digest: str) -> list:
        if digest in self.cache:
            self.cache.move_to_end(digest)
            return self.cache[digest][0]
        reference = self.database.execute(
            "SELECT byte_offset, byte_length FROM toolsets WHERE digest = ?", (digest,)
        ).fetchone()
        if reference is None:
            raise KeyError(digest)
        self.stream.seek(reference[0])
        try:
            record = json.loads(self.stream.read(reference[1]))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid source record for digest {digest!r}") from exc
        if record.get("digest") != digest:
            raise ValueError(f"source offset does not match toolset digest {digest!r}")
        tools = json.loads(record["toolsJson"])
        if isinstance(tools, dict):
            tools = tools.get("tools")
        if not isinstance(tools, list):
            raise ValueError(f"invalid source toolset {digest!r}")
        # The limit accounts for serialized source bytes, not the potentially
        # larger in-memory size of decoded Python objects.
        size = reference[1]
        if size <= self.cache_limit_bytes:
            while self.cache and self.cache_bytes + size > self.cache_limit_bytes:
                _, (_, discarded_size) = self.cache.popitem(last=False)
                self.cache_bytes -= discarded_size
            self.cache[digest] = (tools, size)
            self.cache_bytes += size
        return tools

    def lookup(
        self, digest: str | None, name: str
    ) -> tuple[str, str | None, dict | None]:
        """Return present, absent, ambiguous or missing with verified content."""
        status, expected, ordinal = self.reference(digest, name)
        if status != "present" or digest is None or ordinal is None:
            return status, expected, None
        tools = self._read_toolset(digest)
        if ordinal < 0 or ordinal >= len(tools) or not isinstance(tools[ordinal], dict):
            raise ValueError(f"invalid tool ordinal for {digest!r}")
        tool = tools[ordinal]
        if tool.get("name") != name or definition_hash(tool) != expected:
            raise ValueError(f"source definition does not match index for {digest!r}")
        return "present", expected, deepcopy(tool)

    def reference(
        self, digest: str | None, name: str
    ) -> tuple[str, str | None, int | None]:
        """Read the indexed identity and hash without parsing source tool text."""
        if not digest:
            return "missing_digest", None, None
        if not self.database.execute(
            "SELECT 1 FROM toolsets WHERE digest = ?", (digest,)
        ).fetchone():
            return "missing_toolset", None, None
        matches = self.database.execute(
            "SELECT definition_hash, tool_ordinal, occurrences "
            "FROM definitions WHERE digest = ? AND name = ?",
            (digest, name),
        ).fetchall()
        if not matches:
            return "absent", None, None
        # A repeated name is ambiguous even when duplicate definitions happen
        # to have identical content; never select an arbitrary occurrence.
        if len(matches) != 1 or matches[0][2] != 1:
            return "ambiguous_name", None, None
        expected, ordinal, _ = matches[0]
        return "present", expected, ordinal

    def close(self) -> None:
        self.cache.clear()
        self.cache_bytes = 0
        self.stream.close()
        self.database.close()

    def __enter__(self) -> DefinitionStore:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def compare_legacy_index(index_path: Path, legacy_path: Path) -> dict[str, int | bool]:
    """Compare all definition identities and multiplicities with the old index."""
    with sqlite3.connect(index_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        metadata = dict(db.execute("SELECT key, value FROM metadata"))
        if (
            metadata.get("schema_version") != "2"
            or metadata.get("status") != "complete"
        ):
            raise ValueError("new definition index is incomplete or incompatible")
        db.execute(
            "ATTACH DATABASE ? AS legacy",
            (legacy_path.resolve().as_uri() + "?mode=ro",),
        )
        old_count = db.execute("SELECT count(*) FROM legacy.definitions").fetchone()[0]
        new_count = db.execute("SELECT count(*) FROM main.definitions").fetchone()[0]
        mismatches = db.execute(
            "SELECT count(*) FROM main.definitions AS n "
            "LEFT JOIN legacy.definitions AS o USING (digest, name, definition_hash) "
            "WHERE o.digest IS NULL OR n.occurrences != o.occurrences"
        ).fetchone()[0]
        return {
            "identical": old_count == new_count and mismatches == 0,
            "old_rows": old_count,
            "new_rows": new_count,
            "mismatches": mismatches,
        }
