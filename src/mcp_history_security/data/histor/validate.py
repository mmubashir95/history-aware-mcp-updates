"""Validate assembled eligibility records against reconstructed source history."""

from __future__ import annotations

import json
from itertools import zip_longest
from pathlib import Path

import pyarrow.parquet as pq


def _rows(path: Path):
    for batch in pq.ParquetFile(path).iter_batches(batch_size=1000):
        yield from batch.to_pylist()


def compare_parquet(left: Path, right: Path) -> dict[str, int | bool]:
    """Compare schemas and row values without relying on Parquet byte identity."""
    first = pq.ParquetFile(left)
    second = pq.ParquetFile(right)
    if not first.schema_arrow.equals(second.schema_arrow):
        return {"identical": False, "rows_compared": 0}
    count = 0
    for a, b in zip_longest(
        first.iter_batches(batch_size=1000), second.iter_batches(batch_size=1000)
    ):
        if a is None or b is None or not a.equals(b):
            return {"identical": False, "rows_compared": count}
        count += a.num_rows
    return {"identical": True, "rows_compared": count}


def validate_tool_table(history_path: Path, output_path: Path) -> dict[str, int]:
    """Check candidate identities, target linkage and nested state references."""
    count = 0
    modifications = 0
    eligible_pairs = 0
    for history, row in zip_longest(_rows(history_path), _rows(output_path)):
        if history is None or row is None:
            raise ValueError("history and tool table have unequal populations")
        identity = (history["server_id"], history["tool_name"])
        if identity != (row["server_id"], row["tool_name"]):
            raise ValueError("history and tool table identities differ")
        events = json.loads(history["events_json"])
        if any(
            (left["observed_at"], left["change_id"])
            > (right["observed_at"], right["change_id"])
            for left, right in zip(events, events[1:])
        ):
            raise ValueError(f"events are not ordered for {identity!r}")
        by_id = {
            event["change_id"]: (index, event) for index, event in enumerate(events)
        }
        if len(by_id) != len(events):
            raise ValueError(f"duplicate change ids for {identity!r}")
        modifications += sum(event["recorded_modification"] for event in events)
        target_id = row["target_change_id"]
        if target_id is None:
            if row["max_eligible_k"]:
                raise ValueError(f"eligible history lacks target: {identity!r}")
            count += 1
            continue
        if target_id not in by_id:
            raise ValueError(f"target not found for {identity!r}")
        target_index, target = by_id[target_id]
        if any(
            event["recorded_modification"]
            and (
                event["revision_kind"] not in {"trivial_tool_counter", "unchanged"}
                or "summary_definition_mismatch" in event["issues"]
            )
            for event in events[target_index + 1 :]
        ):
            raise ValueError(f"target is not latest candidate for {identity!r}")
        if (row["target_before_digest"], row["target_after_digest"]) != (
            target["before_digest"],
            target["after_digest"],
        ):
            raise ValueError(f"target reference mismatch for {identity!r}")
        windows = json.loads(row["windows_json"])
        maximum = row["max_eligible_k"]
        eligible = sorted(int(k) for k, value in windows.items() if value["eligible"])
        if eligible != list(range(2, maximum + 1)):
            raise ValueError(f"non-nested eligibility for {identity!r}")
        for k in eligible:
            states = windows[str(k)]["states"]
            if len(states) != k:
                raise ValueError(f"window length mismatch for {identity!r}")
            if k > 2 and windows[str(k - 1)]["states"] != states[-(k - 1) :]:
                raise ValueError(f"non-nested states for {identity!r}")
            for state in states:
                if state["change_id"] not in by_id:
                    raise ValueError(f"unknown state reference for {identity!r}")
                position, event = by_id[state["change_id"]]
                side = state["side"]
                if side not in {"before", "after"} or position > target_index:
                    raise ValueError(f"invalid or post-target state for {identity!r}")
                if (state["toolset_digest"], state["definition_hash"]) != (
                    event[f"{side}_digest"],
                    event[f"{side}_hash"],
                ):
                    raise ValueError(f"state reference mismatch for {identity!r}")
            if (
                states[-2]["toolset_digest"] != target["before_digest"]
                or states[-1]["toolset_digest"] != target["after_digest"]
            ):
                raise ValueError(f"target predecessor mismatch for {identity!r}")
        if "eligible_k2" in row:
            for k in range(2, 21):
                if row[f"eligible_k{k}"] != windows[str(k)]["eligible"]:
                    raise ValueError(f"eligibility flag mismatch for {identity!r}")
        if "later_observations_exist" in row and row["later_observations_exist"] != (
            target_index < len(events) - 1
        ):
            raise ValueError(f"later observation flag mismatch for {identity!r}")
        if maximum >= 2 and "selected_field_coverage_json" in row:
            states = windows[str(maximum)]["states"]
            for column in (
                "selected_field_coverage_json",
                "selected_annotation_states_json",
                "selected_classification_coverage_json",
                "selected_scanner_states_json",
                "selected_launch_states_json",
            ):
                coverage = json.loads(row[column])
                if len(coverage) != len(states) or any(
                    (left["change_id"], left["side"])
                    != (right["change_id"], right["side"])
                    for left, right in zip(coverage, states)
                ):
                    raise ValueError(f"coverage reference mismatch for {identity!r}")
        eligible_pairs += maximum >= 2
        count += 1
    return {
        "candidate_tools": count,
        "recorded_modifications": modifications,
        "eligible_k2": eligible_pairs,
    }
