"""Assemble traceable candidate records from independently generated stages."""

from __future__ import annotations

import json
from itertools import groupby, zip_longest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from .changes import change_version_metadata
from .metadata import annotate_launch_evidence, launch_evidence
from .quality import flapping_indicator


def _rows(path: Path):
    for batch in pq.ParquetFile(path).iter_batches(batch_size=1000):
        yield from batch.to_pylist()


def _history_counts(events: list[dict]) -> dict[str, int]:
    """Count observed content states without collapsing non-adjacent reversions."""
    states: list[str | None] = []
    for index, event in enumerate(events):
        if index and "server_chain_break_before" in event["issues"]:
            states.append(None)
        if index == 0 or "server_chain_break_before" in event["issues"]:
            states.append(event["before_hash"])
        before, after = event["before_hash"], event["after_hash"]
        if set(event["issues"]) - {"server_chain_break_before"}:
            states.append(None)
            if after is not None:
                states.append(after)
            continue
        if after is None or before is None or before != after:
            states.append(after)
    known = [state for state in states if state is not None]
    seen: set[str] = set()
    reversions = 0
    previous = None
    for state in states:
        if state is None:
            seen.clear()
            previous = None
            continue
        if state in seen and state != previous:
            reversions += 1
        seen.add(state)
        previous = state
    substantive_states = 0
    segment_open = False
    for event in events:
        before, after = event["before_hash"], event["after_hash"]
        if "server_chain_break_before" in event["issues"] or before is None:
            segment_open = False
        if before is not None and not segment_open:
            substantive_states += 1
            segment_open = True
        if set(event["issues"]) - {"server_chain_break_before"}:
            if after is not None and after != before:
                substantive_states += 1
            segment_open = after is not None
            continue
        if (
            event["recorded_modification"]
            and event.get("revision_kind") == "substantive_uncertain"
            and before is not None
            and after is not None
            and before != after
        ):
            substantive_states += 1
        if after is None:
            segment_open = False
        elif before is None:
            substantive_states += 1
            segment_open = True
    return {
        "recorded_server_transitions": len(events),
        "recorded_modifications": sum(
            event["recorded_modification"] for event in events
        ),
        "observed_state_count": len(states),
        "known_distinct_definitions": len(set(known)),
        "unknown_state_count": len(states) - len(known),
        "observed_reversions": reversions,
        "substantive_version_states": substantive_states,
    }


def assemble_tool_table(
    history_path: Path,
    assessment_path: Path,
    cluster_path: Path,
    annotation_path: Path,
    scanner_path: Path,
    field_coverage_path: Path,
    classification_path: Path,
    package_observations_path: Path,
    changes_path: Path,
    output_path: Path,
    snapshot: str,
) -> dict[str, int]:
    """Join stages by candidate identity and write a new Parquet artifact."""
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite tool table: {output_path}")
    cluster_rows = {}
    for row in _rows(cluster_path):
        key = (row["server_id"], row["tool_name"])
        if key in cluster_rows:
            raise ValueError("duplicate cluster identity")
        cluster_rows[key] = row

    def grouped(path: Path):
        for key, items in groupby(
            _rows(path), key=lambda row: (row["server_id"], row["tool_name"])
        ):
            yield key, list(items)

    class StateGroups:
        def __init__(self, path: Path):
            self.groups = iter(grouped(path))
            self.current = next(self.groups, None)

        def take(self, identity: tuple[str, str]) -> list[dict]:
            if self.current is None or self.current[0] > identity:
                return []
            if self.current[0] != identity:
                raise ValueError("state coverage identities are not aligned")
            result = self.current[1]
            self.current = next(self.groups, None)
            return result

    annotations = StateGroups(annotation_path)
    fields = StateGroups(field_coverage_path)
    classifications = StateGroups(classification_path)
    launches = launch_evidence(package_observations_path)
    versions = change_version_metadata(changes_path)
    schema_fields = [
        ("server_id", pa.string()),
        ("tool_name", pa.string()),
        ("source_type", pa.string()),
        ("description_language", pa.string()),
        ("server_name", pa.string()),
        ("publisher_name_prefix", pa.string()),
        ("repository", pa.string()),
        ("package_identity", pa.string()),
        ("delisted", pa.bool_()),
        ("target_change_id", pa.int64()),
        ("target_timestamp", pa.string()),
        ("first_recorded_change_timestamp", pa.string()),
        ("target_before_digest", pa.string()),
        ("target_after_digest", pa.string()),
        ("target_recorded_versions_json", pa.string()),
        ("latest_observation_timestamp", pa.string()),
        ("later_observations_exist", pa.bool_()),
        ("latest_after_digest", pa.string()),
        ("max_eligible_k", pa.int32()),
        ("windows_json", pa.large_string()),
        ("cluster_id", pa.string()),
        ("exact_history_signature", pa.string()),
        ("cluster_size", pa.int64()),
        ("representative", pa.bool_()),
        ("cluster_evidence_status", pa.string()),
        ("cluster_matching_methods_json", pa.string()),
        ("flapping_indicator", pa.bool_()),
        ("flapping_cause", pa.string()),
        ("selected_hidden_characters", pa.bool_()),
        ("quality_json", pa.string()),
        ("revision_counts_json", pa.string()),
        ("selected_annotation_states_json", pa.large_string()),
        ("selected_field_coverage_json", pa.large_string()),
        ("selected_classification_coverage_json", pa.large_string()),
        ("selected_scanner_states_json", pa.large_string()),
        ("selected_launch_states_json", pa.large_string()),
        ("target_scanner_json", pa.string()),
        ("target_reintroduced_findings", pa.int64()),
        ("earlier_scanner_findings_status", pa.string()),
        ("target_launch_compatibility", pa.string()),
        ("target_before_launch_signature", pa.string()),
        ("target_after_launch_signature", pa.string()),
        ("snapshot", pa.string()),
    ]
    schema_fields.extend(
        (key, pa.int64())
        for key in (
            "recorded_server_transitions",
            "recorded_modifications",
            "observed_state_count",
            "known_distinct_definitions",
            "unknown_state_count",
            "observed_reversions",
            "substantive_version_states",
            "substantive_recorded_events",
            "trivial_recorded_events",
            "unresolved_recorded_events",
        )
    )
    schema_fields.extend((f"eligible_k{k}", pa.bool_()) for k in range(2, 21))
    schema = pa.schema(schema_fields)
    pending = []
    count = 0
    modifications = 0
    seen = set()
    with pq.ParquetWriter(output_path, schema, compression="zstd") as writer:
        for history, assessment, scanner in zip_longest(
            _rows(history_path), _rows(assessment_path), _rows(scanner_path)
        ):
            if history is None or assessment is None or scanner is None:
                raise ValueError("stage population mismatch")
            identity = (history["server_id"], history["tool_name"])
            if (
                identity in seen
                or identity not in cluster_rows
                or any(
                    (row["server_id"], row["tool_name"]) != identity
                    for row in (assessment, scanner)
                )
            ):
                raise ValueError("duplicate, missing, or misaligned stage identity")
            seen.add(identity)
            events = json.loads(history["events_json"])
            annotate_launch_evidence(
                {"server_id": history["server_id"], "events": events},
                assessment["source_type"],
                launches,
            )
            target = next(
                (
                    event
                    for event in events
                    if event["change_id"] == assessment["target_change_id"]
                ),
                None,
            )
            target_index = events.index(target) if target is not None else -1
            windows = json.loads(assessment["windows_json"])
            cluster = cluster_rows[identity]
            annotation_states = annotations.take(identity)
            field_states = fields.take(identity)
            classification_states = classifications.take(identity)
            revision_counts = json.loads(assessment["revision_counts_json"])
            is_flapping = flapping_indicator(events)
            event_by_id = {event["change_id"]: event for event in events}
            launch_states = []
            if assessment["max_eligible_k"] >= 2:
                for state in windows[str(assessment["max_eligible_k"])]["states"]:
                    event = event_by_id[state["change_id"]]
                    launch_states.append(
                        {
                            "change_id": state["change_id"],
                            "side": state["side"],
                            "compatibility": event["launch_compatibility"],
                            "launch_signature": event.get(
                                f"{state['side']}_launch_signature"
                            ),
                        }
                    )
            row = {
                key: assessment[key]
                for key in (
                    "server_id",
                    "tool_name",
                    "source_type",
                    "server_name",
                    "publisher_name_prefix",
                    "repository",
                    "package_identity",
                    "delisted",
                    "target_change_id",
                    "target_timestamp",
                    "latest_observation_timestamp",
                    "max_eligible_k",
                    "windows_json",
                    "quality_json",
                    "revision_counts_json",
                    "target_launch_compatibility",
                    "target_before_launch_signature",
                    "target_after_launch_signature",
                )
            }
            row.update(
                {
                    "description_language": "unknown",
                    "target_before_digest": target["before_digest"] if target else None,
                    "target_after_digest": target["after_digest"] if target else None,
                    "target_recorded_versions_json": json.dumps(
                        versions[target["change_id"]], sort_keys=True
                    )
                    if target
                    else None,
                    "first_recorded_change_timestamp": events[0]["observed_at"]
                    if events
                    else None,
                    "latest_after_digest": events[-1]["after_digest"]
                    if events
                    else None,
                    "later_observations_exist": target_index >= 0
                    and target_index < len(events) - 1,
                    "cluster_id": cluster["cluster_id"],
                    "exact_history_signature": cluster["exact_history_signature"],
                    "cluster_size": cluster["cluster_size"],
                    "representative": cluster["representative"],
                    "cluster_evidence_status": cluster["evidence_status"],
                    "cluster_matching_methods_json": json.dumps(
                        cluster["matching_methods"]
                    ),
                    "flapping_indicator": is_flapping,
                    "flapping_cause": "unknown" if is_flapping else None,
                    "selected_hidden_characters": any(
                        state["hidden_characters"] for state in field_states
                    )
                    if field_states
                    else None,
                    "substantive_recorded_events": revision_counts.get(
                        "substantive_uncertain", 0
                    ),
                    "trivial_recorded_events": revision_counts.get(
                        "trivial_tool_counter", 0
                    ),
                    "unresolved_recorded_events": revision_counts.get("unknown", 0),
                    "selected_annotation_states_json": json.dumps(
                        annotation_states, separators=(",", ":")
                    ),
                    "selected_field_coverage_json": json.dumps(
                        field_states, separators=(",", ":")
                    ),
                    "selected_classification_coverage_json": json.dumps(
                        classification_states, separators=(",", ":")
                    ),
                    "selected_scanner_states_json": scanner["selected_states_json"],
                    "selected_launch_states_json": json.dumps(
                        launch_states, separators=(",", ":")
                    ),
                    "target_scanner_json": scanner["target_findings_json"],
                    "target_reintroduced_findings": scanner["target_reintroduced"],
                    "earlier_scanner_findings_status": scanner[
                        "earlier_findings_status"
                    ],
                    "snapshot": snapshot,
                }
            )
            row.update(_history_counts(events))
            row.update(
                {f"eligible_k{k}": windows[str(k)]["eligible"] for k in range(2, 21)}
            )
            modifications += row["recorded_modifications"]
            count += 1
            pending.append(row)
            if len(pending) == 1000:
                writer.write_table(pa.Table.from_pylist(pending, schema=schema))
                pending.clear()
        if pending:
            writer.write_table(pa.Table.from_pylist(pending, schema=schema))
    if count != len(cluster_rows) or any(
        group.current is not None for group in (annotations, fields, classifications)
    ):
        raise ValueError("cluster and candidate populations differ")
    return {"candidate_tools": count, "recorded_modifications": modifications}
