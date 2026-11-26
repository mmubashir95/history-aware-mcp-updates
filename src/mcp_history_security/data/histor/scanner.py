"""Read prior WARDEN rescans as coverage and candidate-discovery evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from itertools import zip_longest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .sources import jsonl_records


def load_rescans(directory: Path) -> dict[str, dict[str, list[dict]]]:
    """Load completed rescan shards; absence of a digest means unscanned."""
    paths = sorted(directory.glob("part*.jsonl"))
    if not paths:
        raise FileNotFoundError(f"no rescan shards in {directory}")
    scans: dict[str, dict[str, list[dict]]] = {}
    ruleset = None
    for path in paths:
        if not path.with_suffix(".ok").is_file():
            raise ValueError(f"rescan completion marker missing for {path}")
        for record in jsonl_records(path):
            if not isinstance(record.get("ruleset"), str) or not record["ruleset"]:
                raise ValueError(f"{path}: missing scanner ruleset")
            if ruleset is None:
                ruleset = record["ruleset"]
            elif record["ruleset"] != ruleset:
                raise ValueError(f"{path}: mixed scanner rulesets")
            digest = record["toolSetDigest"]
            if digest in scans:
                raise ValueError(f"duplicate scanned digest {digest!r}")
            findings = record["findings"]
            if not isinstance(findings, list):
                raise ValueError(f"{path}: findings must be a list")
            per_tool: dict[str, list[dict]] = defaultdict(list)
            for finding in findings:
                if not isinstance(finding, dict) or not isinstance(
                    finding.get("tool"), str
                ):
                    raise ValueError(f"{path}: finding lacks a tool name")
                if not isinstance(finding.get("code"), str) or not isinstance(
                    finding.get("tier"), str
                ):
                    raise ValueError(f"{path}: finding lacks a code or tier")
                message = finding.get("message")
                if not isinstance(message, str):
                    raise ValueError(f"{path}: finding lacks a message")
                # Rule and parsed location identify a finding across versions;
                # retain a message hash separately to detect changed messages.
                match = re.match(
                    r'Tool ".*?" (description|input schema|output schema|'
                    r"name|title|annotations|metadata) ",
                    message,
                    re.S,
                )
                locations = {
                    "input schema": "inputSchema",
                    "output schema": "outputSchema",
                }
                location = (
                    locations.get(match.group(1), match.group(1)) if match else None
                )
                per_tool[finding["tool"]].append(
                    {
                        "identity": (finding.get("code"), location),
                        "span_hash": hashlib.sha256(
                            message.encode("utf-8")
                        ).hexdigest(),
                        "code": finding.get("code"),
                        "tier": finding.get("tier"),
                    }
                )
            scans[digest] = dict(per_tool)
    return scans


def compare_findings(
    scans: dict, before: str | None, after: str | None, tool: str
) -> dict:
    """Compare rule/location instances; changed messages remain persistent."""
    # An unscanned side has unknown findings, not an empty or clean result.
    if before not in scans or after not in scans:
        return {
            "coverage": "incomplete",
            "new": None,
            "persistent": None,
            "removed": None,
        }
    previous = scans[before].get(tool, [])
    current = scans[after].get(tool, [])
    unresolved = any(finding["identity"][1] is None for finding in previous + current)
    if unresolved:
        return {
            "coverage": "both_scanned",
            "linkage": "unresolved_location",
            "new": None,
            "persistent": None,
            "persistent_message_changed": None,
            "removed": None,
            "new_block": None,
            "new_advisory": None,
            "before_findings": len(previous),
            "after_findings": len(current),
            "after_block": sum(finding["tier"] == "block" for finding in current),
            "after_advisory": sum(finding["tier"] == "advise" for finding in current),
        }
    old = Counter(finding["identity"] for finding in previous)
    new = Counter(finding["identity"] for finding in current)
    old_spans = Counter(
        (finding["identity"], finding["span_hash"]) for finding in previous
    )
    new_spans = Counter(
        (finding["identity"], finding["span_hash"]) for finding in current
    )
    # Counters preserve multiplicity when the same rule/location appears more
    # than once. A changed message does not by itself make a finding new.
    persistent = sum((new & old).values())
    unchanged = sum((new_spans & old_spans).values())
    introduced = new - old
    introduced_tiers: Counter = Counter()
    for finding in current:
        identity = finding["identity"]
        if introduced[identity] > 0:
            introduced_tiers[finding["tier"]] += 1
            introduced[identity] -= 1
    return {
        "coverage": "both_scanned",
        "new": sum((new - old).values()),
        "persistent": persistent,
        "persistent_message_changed": persistent - unchanged,
        "removed": sum((old - new).values()),
        "before_findings": len(previous),
        "after_findings": len(current),
        "after_block": sum(finding["tier"] == "block" for finding in current),
        "after_advisory": sum(finding["tier"] == "advise" for finding in current),
        "new_block": introduced_tiers["block"],
        "new_advisory": introduced_tiers["advise"],
    }


def load_recorded_scans(path: Path) -> dict[str, dict[str, list[dict]]]:
    """Load original HISTOR scan spans as hashes, without retaining matched text."""
    scans = {}
    for record in jsonl_records(path):
        digest = record["toolSetDigest"]
        if digest in scans:
            raise ValueError(f"duplicate original scanned digest {digest!r}")
        findings = json.loads(record["matchesJson"])
        if not isinstance(findings, list):
            raise ValueError(f"{path}: matchesJson must contain a list")
        per_tool: dict[str, list[dict]] = defaultdict(list)
        for finding in findings:
            if not isinstance(finding, dict) or not isinstance(
                finding.get("tool"), str
            ):
                raise ValueError(f"{path}: recorded finding lacks a tool name")
            span = json.dumps(finding.get("span"), sort_keys=True, ensure_ascii=False)
            where = json.dumps(finding.get("where"), sort_keys=True, ensure_ascii=False)
            per_tool[finding["tool"]].append(
                {
                    "code": finding.get("code"),
                    "where": where,
                    "span_hash": hashlib.sha256(span.encode("utf-8")).hexdigest(),
                }
            )
        scans[digest] = dict(per_tool)
    return scans


def compare_recorded_spans(
    scans: dict, before: str | None, after: str | None, tool: str
) -> dict:
    """Compare spans only when both original scans are available."""
    if before not in scans or after not in scans:
        return {"coverage": "incomplete", "changed_code_locations": None}

    def signatures(digest: str) -> dict:
        groups = defaultdict(set)
        for finding in scans[digest].get(tool, []):
            groups[(finding["code"], finding["where"])].add(finding["span_hash"])
        return groups

    old, new = signatures(before), signatures(after)
    return {
        "coverage": "both_scanned",
        "changed_code_locations": sum(
            old[key] != new[key] for key in old.keys() & new.keys()
        ),
    }


def _rows(path: Path):
    for batch in pq.ParquetFile(path).iter_batches(batch_size=1000):
        yield from batch.to_pylist()


def write_scanner_coverage(
    history_path: Path,
    assessment_path: Path,
    output_path: Path,
    scans: dict,
    recorded_scans: dict | None = None,
) -> dict[str, int]:
    """Record selected-state coverage and target comparisons without tool text."""
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite scanner coverage: {output_path}")
    schema = pa.schema(
        [
            ("server_id", pa.string()),
            ("tool_name", pa.string()),
            ("selected_states_json", pa.large_string()),
            ("target_findings_json", pa.string()),
            ("target_reintroduced", pa.int64()),
            ("prior_coverage_complete", pa.bool_()),
            ("earlier_findings_status", pa.string()),
        ]
    )
    count = 0
    batch_rows = []
    with pq.ParquetWriter(output_path, schema, compression="zstd") as writer:
        for history, assessment in zip_longest(
            _rows(history_path), _rows(assessment_path)
        ):
            if (
                history is None
                or assessment is None
                or (history["server_id"], history["tool_name"])
                != (assessment["server_id"], assessment["tool_name"])
            ):
                raise ValueError("history and assessment identities do not align")
            name = history["tool_name"]
            events = json.loads(history["events_json"])
            target_id = assessment["target_change_id"]
            seen: set[tuple] = set()
            complete = True
            reintroduced = None
            target_findings = {"coverage": "no_target"}
            earlier_status = "no_target"
            for event in events:
                before, after = event["before_digest"], event["after_digest"]
                before_scanned = before in scans
                after_scanned = after in scans
                if not before_scanned or not after_scanned:
                    complete = False
                previous = scans.get(before, {}).get(name, []) if before_scanned else []
                current = scans.get(after, {}).get(name, []) if after_scanned else []
                if any(
                    finding["identity"][1] is None for finding in previous + current
                ):
                    complete = False
                old = {finding["identity"] for finding in previous}
                now = {finding["identity"] for finding in current}
                if event["change_id"] == target_id:
                    target_findings = compare_findings(scans, before, after, name)
                    target_findings["recorded_span_comparison"] = (
                        compare_recorded_spans(
                            recorded_scans or {}, before, after, name
                        )
                    )
                    if seen or old:
                        earlier_status = "observed"
                    elif complete:
                        earlier_status = "none_observed"
                    else:
                        earlier_status = "unknown"
                    # Reintroduction requires complete prior coverage; otherwise
                    # an earlier unobserved occurrence cannot be ruled out.
                    if before_scanned and after_scanned and complete:
                        reintroduced = len((now - old) & seen)
                    break
                if before_scanned:
                    seen.update(old)
                if after_scanned:
                    seen.update(now)
            selected = []
            k = assessment["max_eligible_k"]
            if k >= 2:
                for state in json.loads(assessment["windows_json"])[str(k)]["states"]:
                    digest = state["toolset_digest"]
                    findings = scans.get(digest, {}).get(name, [])
                    selected.append(
                        {
                            "change_id": state["change_id"],
                            "side": state["side"],
                            "coverage": "scanned" if digest in scans else "unscanned",
                            "findings": len(findings) if digest in scans else None,
                        }
                    )
            batch_rows.append(
                {
                    "server_id": history["server_id"],
                    "tool_name": name,
                    "selected_states_json": json.dumps(selected, separators=(",", ":")),
                    "target_findings_json": json.dumps(target_findings, sort_keys=True),
                    "target_reintroduced": reintroduced,
                    "prior_coverage_complete": complete
                    if target_id is not None
                    else None,
                    "earlier_findings_status": earlier_status,
                }
            )
            count += 1
            if len(batch_rows) == 1000:
                writer.write_table(pa.Table.from_pylist(batch_rows, schema=schema))
                batch_rows.clear()
        if batch_rows:
            writer.write_table(pa.Table.from_pylist(batch_rows, schema=schema))
    return {"candidate_tools": count}
