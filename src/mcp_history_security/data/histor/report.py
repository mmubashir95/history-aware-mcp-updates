"""Generate a traceable research readout from validated local artifacts."""

from __future__ import annotations

import csv
import gzip
import html
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from itertools import zip_longest
from pathlib import Path

import pyarrow.parquet as pq
import yaml

from .index import DefinitionStore
from .sources import jsonl_records
from .statistics import feasibility_status


def _rows(path: Path):
    for batch in pq.ParquetFile(path).iter_batches(batch_size=1000):
        yield from batch.to_pylist()


def _safe(value: object) -> str:
    """Escape untrusted identity text for Markdown tables."""
    rendered = json.dumps(value, ensure_ascii=True)
    if isinstance(value, str):
        rendered = rendered[1:-1]
    return (
        html.escape(rendered, quote=True).replace("|", "&#124;").replace("`", "&#96;")
    )


def _summary_funnel(path: Path) -> list[dict[str, str]]:
    """Select the all-source structural and simulated stages for the report."""
    with path.open(encoding="utf-8", newline="") as stream:
        return [
            row
            for row in csv.DictReader(stream)
            if row["source_type"] == "all"
            and row["stage_id"] in {"nested_history", "simulated_dedup"}
            and int(row["history_length"]) in {2, 3, 4, 5, 10, 20}
        ]


def _target_hidden_presence(states: list[dict]) -> str | None:
    """Describe presence changes for the final predecessor/target pair."""
    if len(states) < 2:
        return None
    before = states[-2]["hidden_characters"]
    after = states[-1]["hidden_characters"]
    if not before and after:
        return "introduced"
    if before and not after:
        return "removed"
    if before and after:
        return "present_both"
    return None


def _audit_context(snapshot_dir: Path, audit_dir: Path) -> dict:
    """Recalculate prior audit context without printing untrusted findings."""
    digests = Counter(
        server["toolSetDigest"]
        for server in jsonl_records(snapshot_dir / "servers.jsonl")
        if not server["delisted"] and server.get("toolSetDigest")
    )
    latest_tools = 0
    parts = sorted((audit_dir / "02_parts").glob("part*.tsv.gz"))
    if not parts:
        raise FileNotFoundError("original toolset index shards are unavailable")
    for path in parts:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                latest_tools += digests.get(line.partition("\t")[0], 0)
    modified_flagged = set()
    for row in jsonl_records(audit_dir / "03_scanner_candidates_full.jsonl"):
        if (
            row["scanner"] == "WARDEN"
            and row["status"] == "NEW"
            and row["tier_or_severity"] == "block"
            and row["tool_change"] != ["ADDED"]
        ):
            modified_flagged.add((row["serverId"], row["tool"]))
    combinations: Counter = Counter()
    names_only = 0
    out_of_order = 0
    same_time = 0
    previous_time = {}
    for row in jsonl_records(snapshot_dir / "changes.jsonl"):
        previous = previous_time.get(row["serverId"])
        if previous is not None:
            out_of_order += row["observedAt"] < previous
            same_time += row["observedAt"] == previous
        previous_time[row["serverId"]] = row["observedAt"]
        summary = json.loads(row["summaryJson"])
        names_only += summary.get("detail") == "names-only"
        for change in summary.get("modified", []):
            combinations["+".join(sorted(change.get("fields", {}))) or "no_fields"] += 1
    extras_times = [
        row["observedAt"]
        for row in jsonl_records(snapshot_dir / "extras_changes.jsonl")
        if row.get("toExtrasDigest") is not None
    ]
    package_extras_times = [
        row["observedAt"]
        for row in jsonl_records(snapshot_dir / "package_observations.jsonl")
        if row.get("toolExtrasDigest") is not None
    ]
    return {
        "latest_listed_servers": sum(digests.values()),
        "latest_tools": latest_tools,
        "modified_flagged_tools": len(modified_flagged),
        "names_only_server_changes": names_only,
        "source_time_out_of_order": out_of_order,
        "source_same_timestamp": same_time,
        "earliest_extras_change": min(extras_times, default=None),
        "earliest_package_extras_observation": min(package_extras_times, default=None),
        "field_combinations": dict(combinations),
    }


def write_research_report(
    table_path: Path,
    history_path: Path,
    distribution_path: Path,
    scenarios_path: Path,
    original_audit_dir: Path,
    raw_manifest_path: Path,
    definition_index_path: Path,
    config_path: Path,
    output_path: Path,
    annotation_change_path: Path | None = None,
    revision_pattern_path: Path | None = None,
) -> dict:
    """Write a provisional report; counts retain their actual unit and coverage."""
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite research report: {output_path}")
    source_counts = Counter()
    eligible_sources = Counter()
    publishers = Counter()
    candidate_publishers = set()
    candidate_repositories = set()
    eligible_repositories = set()
    missing_publishers = Counter()
    quality = Counter()
    revisions = Counter()
    scanner = Counter()
    annotations = Counter()
    fields = Counter()
    annotations_by_source = defaultdict(Counter)
    fields_by_source = defaultdict(Counter)
    target_hidden_presence = Counter()
    classifications = Counter()
    launch = Counter()
    exact_signatures = Counter()
    cluster_sizes = {}
    pipeworx = Counter()
    pipeworx_clusters = set()
    durations: dict[str, list[float]] = defaultdict(list)
    intervals: dict[str, list[float]] = defaultdict(list)
    same_day_intervals: Counter = Counter()
    targets = []
    examples = {}
    criteria = {}
    used_examples = set()
    longest = None
    flapping = 0
    flapping_k2 = 0
    flapping_k4 = 0
    reversion_events = 0
    histories_with_reversions = 0
    total = 0
    modifications = 0
    for history, row in zip_longest(_rows(history_path), _rows(table_path)):
        if history is None or row is None:
            raise ValueError("history and report input counts differ")
        identity = (row["server_id"], row["tool_name"])
        if identity != (history["server_id"], history["tool_name"]):
            raise ValueError("history and report input identities differ")
        events = json.loads(history["events_json"])
        total += 1
        modifications += row["recorded_modifications"]
        source = row["source_type"]
        source_counts[source] += 1
        if row["publisher_name_prefix"] is None:
            missing_publishers["candidate"] += 1
        else:
            candidate_publishers.add(row["publisher_name_prefix"])
        if row["repository"]:
            candidate_repositories.add(row["repository"])
        if row["eligible_k2"]:
            eligible_sources[source] += 1
            if row["publisher_name_prefix"] is not None:
                publishers[row["publisher_name_prefix"]] += 1
            else:
                missing_publishers["eligible_k2"] += 1
            if row["repository"]:
                eligible_repositories.add(row["repository"])
        quality.update(json.loads(row["quality_json"]))
        revisions.update(json.loads(row["revision_counts_json"]))
        launch[row["target_launch_compatibility"]] += 1
        exact_signatures[row["exact_history_signature"]] += 1
        cluster_sizes[row["cluster_id"]] = row["cluster_size"]
        finding = json.loads(row["target_scanner_json"])
        scanner["target_" + finding["coverage"]] += 1
        for key in (
            "new",
            "persistent",
            "persistent_message_changed",
            "removed",
            "new_block",
            "new_advisory",
            "after_block",
            "after_advisory",
        ):
            scanner[key] += finding.get(key) or 0
        scanner["target_with_prior_findings"] += (
            finding.get("before_findings") or 0
        ) > 0
        scanner["earlier_findings_" + row["earlier_scanner_findings_status"]] += 1
        scanner["reintroduced_exact_identities"] += (
            row["target_reintroduced_findings"] or 0
        )
        for state in json.loads(row["selected_scanner_states_json"]):
            scanner["selected_" + state["coverage"]] += 1
        for state in json.loads(row["selected_annotation_states_json"]):
            annotations[state["annotation_status"]] += 1
            annotations_by_source[source][state["annotation_status"]] += 1
        selected_fields = json.loads(row["selected_field_coverage_json"])
        for state in selected_fields:
            for key in ("description", "input_schema", "output_schema"):
                fields[f"{key}_{state[key]}"] += 1
                fields_by_source[source][f"{key}_{state[key]}"] += 1
            fields["hidden_character_states"] += bool(state["hidden_characters"])
        hidden_transition = _target_hidden_presence(selected_fields)
        if hidden_transition:
            target_hidden_presence[hidden_transition] += 1
        for state in json.loads(row["selected_classification_coverage_json"]):
            classifications[state["coverage"]] += 1
        if row["publisher_name_prefix"] == "io.github.pipeworx-io":
            pipeworx["candidate"] += 1
            pipeworx["with_substantive_or_uncertain_target"] += (
                row["target_change_id"] is not None
            )
            pipeworx["eligible_k2"] += row["eligible_k2"]
            pipeworx["eligible_k4"] += row["eligible_k4"]
            if row["eligible_k4"]:
                pipeworx_clusters.add(row["cluster_id"])
        if events:
            times = [
                datetime.fromisoformat(event["observed_at"].replace("Z", "+00:00"))
                for event in events
            ]
            durations[source].append((times[-1] - times[0]).total_seconds() / 86400)
            substantive = [
                time
                for time, event in zip(times, events)
                if event["recorded_modification"]
                and event["revision_kind"] == "substantive_uncertain"
            ]
            intervals[source].extend(
                (b - a).total_seconds() / 86400
                for a, b in zip(substantive, substantive[1:])
            )
            same_day_intervals[source] += sum(
                a.date() == b.date() for a, b in zip(substantive, substantive[1:])
            )
        if row["target_timestamp"]:
            targets.append(row["target_timestamp"])
        if longest is None or row["max_eligible_k"] > longest["max_eligible_k"]:
            longest = row
        is_flapping = row["flapping_indicator"]
        reversion_events += row["observed_reversions"]
        histories_with_reversions += row["observed_reversions"] > 0
        flapping += is_flapping
        flapping_k2 += is_flapping and row["eligible_k2"]
        flapping_k4 += is_flapping and row["eligible_k4"]
        target_index = next(
            (
                i
                for i, event in enumerate(events)
                if event["change_id"] == row["target_change_id"]
            ),
            -1,
        )
        prior_break = target_index >= 0 and any(
            "server_chain_break_before" in event["issues"]
            for event in events[: target_index + 1]
        )
        window_decisions = json.loads(row["windows_json"])
        k4_reason = window_decisions["4"]["reason"] or ""
        criteria = {
            "valid two-state window": row["eligible_k2"],
            "valid four-state window": row["eligible_k4"],
            "valid five-state window": row["eligible_k5"],
            "valid ten-state window": row["eligible_k10"],
            "recognized counter churn": json.loads(row["revision_counts_json"]).get(
                "trivial_tool_counter", 0
            )
            > 0,
            "unknown state": row["unknown_state_count"] > 0,
            "names-only window exclusion": "names_only" in k4_reason,
            "insufficient context exclusion": "insufficient_history" in k4_reason,
            "different package launch exclusion": row["target_launch_compatibility"]
            == "different",
            "eligible window with earlier chain break": row["eligible_k2"]
            and prior_break,
            "observed oscillation": is_flapping,
            "recorded reversion": row["observed_reversions"] > 0,
            "shared-state or template cluster": row["cluster_size"] > 1,
            "member of numeric-description-linked cluster": (
                "numeric_description_template"
                in json.loads(row["cluster_matching_methods_json"])
            ),
            "package source": source in {"npm", "pypi"},
            "remote source": source == "remote",
            "target with block-tier finding": (finding.get("after_block") or 0) > 0,
        }
        for label, matches in criteria.items():
            if matches and label not in examples and identity not in used_examples:
                examples[label] = (row, events)
                used_examples.add(identity)
                break
    with distribution_path.open(encoding="utf-8", newline="") as stream:
        distribution = list(csv.DictReader(stream))
    with (distribution_path.parent / "exclusion_reasons.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        exclusions = {
            (row["reason"], int(row["history_length"])): int(row["candidate_tools"])
            for row in csv.DictReader(stream)
            if row["source_type"] == "all"
        }
    funnel = _summary_funnel(distribution_path.parent / "eligibility_funnel.csv")
    scenarios = json.loads(scenarios_path.read_text(encoding="utf-8"))
    old_history = json.loads(
        (original_audit_dir / "04_history_summary.json").read_text(encoding="utf-8")
    )
    old_revision = json.loads(
        (original_audit_dir / "05_revision_substance.json").read_text(encoding="utf-8")
    )
    old_substantive = old_revision["tools_by_substantive_revisions(versions=revs+1)"]
    old_scanner = json.loads(
        (original_audit_dir / "03_scanner_linkage_full.json").read_text(
            encoding="utf-8"
        )
    )
    raw_manifest = json.loads(raw_manifest_path.read_text(encoding="utf-8"))
    configuration = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    minimum_clusters = configuration["eligibility"].get("minimum_independent_clusters")
    audit_context = _audit_context(raw_manifest_path.parent, original_audit_dir)
    lines = [
        "# HISTOR eligibility and data quality assessment",
        "",
        "**Status: provisional; independent review and remaining verification "
        "required.**",
        "",
        "## Executive summary",
        "",
        f"The candidate population contains {total:,} individual server/tool "
        f"identities and {modifications:,} recorded modification events. Source "
        f"data are observations, not a complete release history. The window "
        f"counts below are structural decisions under the rules documented in "
        f"ADR 002. They are not labels or proof of training sufficiency.",
        "",
        "## Source and provenance",
        "",
        f"Snapshot: {raw_manifest['createdAt']}; recorded change interval: "
        f"{raw_manifest['changesFrom']} to {raw_manifest['changesUntil']}. The "
        f"manifest's gzip hashes do not authenticate the available decompressed "
        f"JSONL files. All manifest row counts were checked; local file hashes "
        f"were recorded separately.",
        "",
        "Source types are inferred from the current server endpoint, not "
        "historical launch identity. Publisher counts use the server-name "
        "prefix as a proxy, not a verified publisher identity. Unknown "
        "categories remain explicit.",
        "",
        "| Source | Candidates | Eligible k≥2 |",
        "| --- | ---: | ---: |",
    ]
    for source in sorted(source_counts):
        lines.append(
            f"| {source} | {source_counts[source]:,} | {eligible_sources[source]:,} |"
        )
    lines.extend(
        [
            "",
            "## Historical definitions and rules",
            "",
            "A distinct definition is a full canonicalized tool object hash. "
            "Chronological states retain reversions; a modification event and "
            "a distinct definition are different units. The primary target is "
            "the latest recorded substantive or uncertain modification. k "
            "includes that target and its actual immediate predecessor. "
            "Earlier context is selected from substantive states, and unknown "
            "transitions or incompatible recorded launch settings are not "
            "bridged. Unrecognized changes are conservatively substantive; "
            "only a narrow tool-count description pattern is treated as "
            "trivial.",
            "",
            "Independent window decisions start from the candidate population. "
            "The funnel separately shows nested structural gates and simulated "
            "deduplication. See `eligibility_funnel.csv` "
            "and `exclusion_reasons.csv`; exclusion reasons can overlap. No "
            "scanner finding, classification or annotation determines "
            "structural eligibility.",
            "",
            "| Rule | Decision | k=2 excluded | k=4 excluded |",
            "| --- | --- | ---: | ---: |",
            f"| W01 | No substantive target | "
            f"{exclusions.get(('no_substantive_target', 2), 0):,} | "
            f"{exclusions.get(('no_substantive_target', 4), 0):,} |",
            f"| W02 | Unknown selected state | "
            f"{exclusions.get(('unresolved_state', 2), 0):,} | "
            f"{exclusions.get(('unresolved_state', 4), 0):,} |",
            f"| W03 | Names-only transition | "
            f"{exclusions.get(('names_only', 2), 0):,} | "
            f"{exclusions.get(('names_only', 4), 0):,} |",
            f"| W04 | Chain break crossed | "
            f"{exclusions.get(('server_chain_break', 2), 0):,} | "
            f"{exclusions.get(('server_chain_break', 4), 0):,} |",
            f"| W05 | Different recorded launch configuration | "
            f"{exclusions.get(('launch_configuration_changed', 2), 0):,} | "
            f"{exclusions.get(('launch_configuration_changed', 4), 0):,} |",
            f"| W06 | Insufficient recorded context | "
            f"{exclusions.get(('insufficient_history', 2), 0):,} | "
            f"{exclusions.get(('insufficient_history', 4), 0):,} |",
            "",
            "Exclusions overlap; rule counts cannot be added to obtain the total.",
            "The `beyond_history_bound` category in the exclusion CSV applies "
            "when k exceeds a candidate's computed evaluation bound; it is "
            "not an additional observed data-quality defect.",
            "",
            "W01 selects the latest recorded substantive or uncertain change; "
            "no earlier target substitutes for an unresolved latest target. "
            "W02–W04 prevent a selected window from crossing an unresolved "
            "state, names-only event or broken digest chain. A break before "
            "the selected window does not exclude a verified suffix; see the "
            "earlier-chain-break example below. W05 blocks a transition with "
            "known different package launch configurations; missing launch "
            "evidence stays unknown. W06 requires enough recorded context. "
            "A same-time ambiguity, a source-summary/definition contradiction "
            "or an unknown target also blocks the affected window. These "
            "conditions are evaluated from event issues in `windows.py`; "
            "zero counts here do not prove they cannot occur in other snapshots.",
            "",
            "### Nested structural funnel and deduplication simulation",
            "",
            "Each structural stage uses the previous shorter window's "
            "population for the same target, including lengths omitted "
            "from this summary. The deduplication rows are "
            "separate simulations, not structural exclusions. Full results "
            "for every length and source are in `eligibility_funnel.csv`.",
            "",
            "| Stage | k | Input tools | Remaining | Excluded |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in funnel:
        label = (
            "structural context"
            if item["stage_id"] == "nested_history"
            else "simulated deduplication"
        )
        lines.append(
            f"| {label} | {item['history_length']} | "
            f"{int(item['input_population']):,} | "
            f"{int(item['remaining_population']):,} | "
            f"{int(item['excluded_population']):,} |"
        )
    lines.extend(
        [
            "",
            "## History length and diversity",
            "",
            "Leakage clusters connect histories sharing a selected definition "
            "or a documented numeric-description template, transitively. They "
            "are conservative grouping estimates, not established "
            "statistically independent samples. Longer-window counts use the "
            "same target as shorter suffixes.",
            "",
            "| k | Exact maximum k | Eligible tools (≥k) | Leakage clusters | "
            "Servers | "
            "Publisher-name prefixes | Minimum rule |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    selected_lengths = set(range(2, 11)) | {15, 20}
    for item in distribution:
        if (
            item["source_type"] == "all"
            and int(item["history_length"]) in selected_lengths
        ):
            feasibility = feasibility_status(
                int(item["unique_leakage_clusters"]), minimum_clusters
            )
            lines.append(
                f"| {item['history_length']} | "
                f"{int(item['exact_max_eligible_count']):,} | "
                f"{int(item['cumulative_eligible_count']):,} | "
                f"{int(item['unique_leakage_clusters']):,} | "
                f"{int(item['unique_servers']):,} | "
                f"{int(item['unique_publisher_name_prefixes']):,} | "
                f"{feasibility} "
                f"|"
            )
    if longest is not None:
        lines.extend(
            [
                "",
                f"The longest structurally eligible history has "
                f"k={longest['max_eligible_k']:,}; "
                f"server `{_safe(longest['server_id'])}`, "
                f"tool `{_safe(longest['tool_name'])}`, "
                f"target change {longest['target_change_id']}. "
                "Full state references are "
                "available in the tool eligibility table.",
            ]
        )
    lines.extend(
        [
            "",
            "### History lengths by source type",
            "",
            "| Source | k | Eligible tools | Leakage clusters | Servers | "
            "Publisher-name prefixes |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in distribution:
        if item["source_type"] != "all" and int(item["history_length"]) in {
            2,
            4,
            5,
            10,
            20,
        }:
            lines.append(
                f"| {item['source_type']} | {item['history_length']} | "
                f"{int(item['cumulative_eligible_count']):,} | "
                f"{int(item['unique_leakage_clusters']):,} | "
                f"{int(item['unique_servers']):,} | "
                f"{int(item['unique_publisher_name_prefixes']):,} |"
            )
    lines.extend(
        [
            "",
            f"Mechanical A→B→A→B→A oscillation was observed in {flapping:,} "
            f"candidate histories. Its cause is unknown; no automatic exclusion "
            f"is applied. "
            f"There are {reversion_events:,} observed reversion events across "
            f"{histories_with_reversions:,} candidate histories. "
            f"{sum(count > 1 for count in exact_signatures.values()):,} exact "
            f"observed-history signatures have multiple members. Unknown states "
            f"prevent asserting an exact signature match.",
            f"If all mechanically oscillating histories were excluded, the "
            f"eligible k=2 and k=4 populations would fall by {flapping_k2:,} "
            f"and {flapping_k4:,}, respectively. This is a sensitivity "
            f"scenario, not the structural eligibility policy.",
            "",
            "## Duplicate and concentration analysis",
            "",
            f"Candidate histories contain {len(candidate_publishers):,} distinct "
            f"publisher-name prefixes and {len(candidate_repositories):,} distinct "
            f"nonempty repository references; the k≥2 population contains "
            f"{len(publishers):,} prefixes and {len(eligible_repositories):,} "
            f"repository references. Missing prefix counts are "
            f"{missing_publishers['candidate']:,} candidates and "
            f"{missing_publishers['eligible_k2']:,} k≥2 eligible tools. "
            "References are counted as recorded, without identity normalization.",
            "",
            f"Leakage cluster-size distribution: singleton "
            f"{sum(size == 1 for size in cluster_sizes.values()):,}, "
            f"2–5 {sum(2 <= size <= 5 for size in cluster_sizes.values()):,}, "
            f"6–20 {sum(6 <= size <= 20 for size in cluster_sizes.values()):,}, "
            f"over 20 {sum(size > 20 for size in cluster_sizes.values()):,}. "
            "These are clusters across all candidates, including unresolved "
            "singletons.",
            "",
            f"The `io.github.pipeworx-io` name-prefix proxy contributes "
            f"{pipeworx['candidate']:,} candidates, "
            f"{pipeworx['with_substantive_or_uncertain_target']:,} with a "
            f"substantive or unresolved target, {pipeworx['eligible_k2']:,} k≥2 "
            f"candidates, and {pipeworx['eligible_k4']:,} k≥4 candidates across "
            f"{len(pipeworx_clusters):,} k≥4 leakage clusters. The denominator "
            f"for each figure is the corresponding candidate or eligible "
            f"population.",
            "",
            "Top name prefixes among k≥2 candidates:",
            "",
        ]
    )
    lines.extend(
        f"- {_safe(name)}: {count:,}" for name, count in publishers.most_common(10)
    )
    lines.extend(
        [
            "",
            "Representative selection is deterministic and occurs before cap "
            "simulations. Missing publisher prefixes are not capped as if they "
            "were one verified publisher. Configured caps are sensitivity "
            "scenarios, not approved final caps; see "
            "`selection_scenarios.json`.",
            "",
            "| Scenario | k | Eligible cluster representatives | Selected | "
            "Servers | Publisher prefixes | Repository references | "
            "Missing publisher selected |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for scenario in scenarios:
        if scenario["history_length"] in {2, 4, 5, 10, 20}:
            diversity = [
                f"{scenario[key]:,}" if key in scenario else "unavailable"
                for key in (
                    "distinct_servers",
                    "distinct_publisher_name_prefixes",
                    "distinct_repository_references",
                )
            ]
            lines.append(
                f"| {_safe(scenario['scenario'])} | "
                f"{scenario['history_length']} | "
                f"{scenario['eligible_cluster_representatives']:,} | "
                f"{scenario['selected']:,} | "
                f"{' | '.join(diversity)} | "
                f"{scenario['missing_publisher_selected']:,} |"
            )
    lines.extend(
        [
            "",
            "## Revision and quality indicators",
            "",
            f"Recorded modification categories: `{dict(revisions)}`. Source "
            f"summary field combinations: "
            f"`{audit_context['field_combinations']}`. Unknown and unrecognized "
            f"revisions are not called benign. Per-tool-transition quality "
            f"events (not unique server changes): `{dict(quality)}`. The source "
            f"contains {audit_context['names_only_server_changes']:,} "
            f"names-only server changes under the original definition. The "
            f"first observed state is left-censored; unknown states and gaps do "
            f"not invalidate a later complete suffix, but they cannot be "
            f"bridged.",
            f"In source order, {audit_context['source_time_out_of_order']:,} "
            f"server changes moved backward in time and "
            f"{audit_context['source_same_timestamp']:,} shared the previous "
            f"server-change timestamp; same-time histories are marked ambiguous.",
            "Annotation availability is measured below; availability alone "
            "cannot establish whether values changed.",
            "",
            "## Temporal characteristics",
            "",
            "Durations below run from the first to last recorded server change "
            "in each candidate history; the first before-state's true "
            "observation time is not inferred. Intervals are between recorded "
            "substantive or uncertain tool modifications. Units are days.",
            "",
            "| Source | Histories | Duration min / median / mean / max | "
            "Update interval min / median / mean / max | Same-day updates |",
            "| --- | ---: | --- | --- | ---: |",
        ]
    )
    if revision_pattern_path is None:
        insert_at = lines.index("## Temporal characteristics") - 1
        lines.insert(insert_at, "Textual revision-pattern counts were not supplied.")
    else:
        patterns = json.loads(revision_pattern_path.read_text(encoding="utf-8"))
        insert_at = lines.index("## Temporal characteristics") - 1
        lines.insert(
            insert_at,
            f"Among {patterns['recorded_modifications']:,} recorded modification "
            f"events, {patterns['counts'].get('whitespace_only_candidate', 0):,} "
            f"are description-only whitespace-pattern candidates and "
            f"{patterns['counts'].get('iso_date_only_candidate', 0):,} are "
            f"description-only ISO-date-pattern candidates. These mechanical "
            f"patterns can be security-relevant, may overlap and are not "
            f"classified as trivial. {patterns['unresolved_events']:,} events "
            f"could not be resolved for this analysis.",
        )
    if revisions.get("trivial_tool_counter", 0) == 0:
        insert_at = lines.index("## Temporal characteristics") - 1
        lines.insert(
            insert_at,
            "The standalone counter rule identified no trivial modification "
            "events. Numeric-description templates are grouping candidates "
            "only; their changes remain substantive or uncertain pending review.",
        )
    for source in sorted(durations):
        values = durations[source]
        delta = intervals[source]
        interval_summary = (
            f"{min(delta):.2f} / {statistics.median(delta):.2f} / "
            f"{statistics.mean(delta):.2f} / "
            f"{max(delta):.2f}"
            if delta
            else "unavailable"
        )
        lines.append(
            f"| {source} | {len(values):,} | {min(values):.2f} / "
            f"{statistics.median(values):.2f} / {statistics.mean(values):.2f} / "
            f"{max(values):.2f} | {interval_summary} | "
            f"{same_day_intervals[source]:,} |"
        )
    lines.extend(
        [
            "",
            "Update intervals are also grouped by elapsed time below. "
            "Each interval is between consecutive recorded modifications "
            "within the same candidate history; it is not proof that all "
            "intermediate real-world updates were observed.",
            "",
            "| Source | Under 1 day | 1 to under 7 days | 7 days or more |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for source in sorted(durations):
        delta = intervals[source]
        lines.append(
            f"| {_safe(source)} | {sum(value < 1 for value in delta):,} | "
            f"{sum(1 <= value < 7 for value in delta):,} | "
            f"{sum(value >= 7 for value in delta):,} |"
        )
    if targets:
        lines.extend(
            [
                "",
                f"Observed target timestamps range from {min(targets)} to "
                f"{max(targets)}.",
            ]
        )
    lines.extend(
        [
            "",
            "## Scanner, classification and field coverage",
            "",
            f"Target-level scanner summary: `{dict(scanner)}`. WARDEN finding "
            f"identity is rule and location; changed messages remain persistent "
            f"and original-scan span comparison is available only when both "
            f"original scans exist. Counts are candidate-target or "
            f"selected-state counts as indicated, not labels. Reintroduction is "
            f"reported only when prior coverage is complete.",
            "",
            f"Annotation availability across selected states: "
            f"`{dict(annotations)}`. Exact-time extras linkage is conservative; "
            f"unknown does not mean absent or false. Selected-state definition "
            f"field coverage: `{dict(fields)}`. Advisory LLM classification "
            f"availability across selected states: `{dict(classifications)}`; "
            f"classification truncation is retained in the companion records.",
            f"For eligible target pairs, hidden-character presence was "
            f"introduced in {target_hidden_presence['introduced']:,}, removed "
            f"in {target_hidden_presence['removed']:,}, and present on both "
            f"sides in {target_hidden_presence['present_both']:,}. Presence on "
            f"both sides does not establish whether the characters changed.",
            "",
            "Selected-state field and annotation availability by source type "
            "(counts describe states, not unique tools):",
            "",
            "| Source | Description present | Input schema present | "
            "Output schema present | Annotation present | Annotation unknown |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for source in sorted(source_counts):
        source_fields = fields_by_source[source]
        source_annotations = annotations_by_source[source]
        unknown_annotations = (
            source_annotations["unknown"] + source_annotations["unresolved_reference"]
        )
        lines.append(
            f"| {_safe(source)} | {source_fields['description_present']:,} | "
            f"{source_fields['input_schema_present']:,} | "
            f"{source_fields['output_schema_present']:,} | "
            f"{source_annotations['present']:,} | "
            f"{unknown_annotations:,} |"
        )
    if annotation_change_path is None:
        lines.extend(
            [
                "",
                "Annotation-value change counts were not supplied for this report.",
            ]
        )
    else:
        summary = json.loads(annotation_change_path.read_text(encoding="utf-8"))
        lines.extend(
            [
                "",
                "Annotation-value comparisons for structurally eligible k=2 "
                "target transitions use exact-time extras links. Unknown "
                "includes unresolved coverage; the results are not labels. "
                "Annotation-only changes without a selected tool modification "
                "are outside this count.",
                "",
                "| Source | Changed | Unchanged | Unknown |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for source, counts in sorted(summary["counts"].items()):
            lines.append(
                f"| {_safe(source)} | {counts.get('changed', 0):,} | "
                f"{counts.get('unchanged', 0):,} | {counts.get('unknown', 0):,} |"
            )
    lines.extend(
        [
            "",
            f"Target package-launch evidence: `{dict(launch)}`. Matching or "
            f"differing recorded launch metadata is evidence only; null or "
            f"multiple configurations remain unknown. Different recorded "
            f"configurations block the affected transition under this "
            f"conservative analysis.",
            f"The earliest non-null extras-change destination was observed at "
            f"{audit_context['earliest_extras_change'] or 'unavailable'}; the "
            f"earliest non-null package extras observation was at "
            f"{audit_context['earliest_package_extras_observation'] or 'unavailable'}. "
            f"These observations do not establish when every tool first supplied "
            f"annotations.",
            "",
            "## Prior audit reconciliation",
            "",
            "| Original metric | Recomputed under original methodology |",
            "| --- | ---: |",
            f"| Latest-list tools in listed servers | "
            f"{audit_context['latest_tools']:,} |",
            f"| Listed servers with latest toolsets | "
            f"{audit_context['latest_listed_servers']:,} |",
            f"| Modified tools | {old_history['counters']['tools']:,} |",
            f"| Modification events | {old_revision['counters']['mods']:,} |",
            f"| ≥2 distinct definitions | "
            f"{old_history['tools_by_distinct_versions']['>=2']:,} |",
            f"| ≥3 distinct definitions | "
            f"{old_history['tools_by_distinct_versions']['>=3']:,} |",
            f"| ≥4 distinct definitions | "
            f"{old_history['tools_by_distinct_versions']['>=4']:,} |",
            f"| ≥4 distinct definitions, old flapping policy | "
            f"{old_history['tools_by_distinct_versions_excluding_flapping']['>=4']:,} "
            f"|",
            f"| ≥2 versions, old substantive rule | {old_substantive['>=1revs']:,} |",
            f"| ≥3 versions, old substantive rule | {old_substantive['>=2revs']:,} |",
            f"| ≥4 versions, old substantive rule | {old_substantive['>=3revs']:,} |",
            f"| ≥5 versions, old substantive rule | {old_substantive['>=4revs']:,} |",
            f"| ≥10 versions, old substantive rule | {old_substantive['>=9revs']:,} |",
            f"| Trivial events, old rule | {old_revision['counters']['trivial']:,} |",
            f"| New block-tier finding instances, old linkage | "
            f"{old_scanner['change_linkage']['WARDEN_NEW_block']:,} |",
            f"| Modified tools with new block-tier finding, old linkage | "
            f"{audit_context['modified_flagged_tools']:,} |",
            "",
            "These original-method counts come from the supplied previous "
            "audit outputs and their input index. See the implementation "
            "report for any independent rerun. The old history script skips unknown "
            "states for its distinct-count analysis and the old revision "
            "heuristic is broader. The values are therefore not sequential "
            "filters or expected totals for this assessment.",
            "",
            "## Traceable historical examples",
            "",
            "Each row references source change IDs and toolset digests. Tool "
            "text is intentionally not reproduced; open the referenced source "
            "records as inert data for detailed inspection. Times in ordered "
            "references are change observation times, not inferred timestamps "
            "for the preceding state.",
            "",
            "| Category | Server / exact tool name | Target and timestamp | "
            "Source | k maximum | Changed definition fields |",
            "| --- | --- | --- | --- | ---: | --- |",
        ]
    )
    with DefinitionStore(
        definition_index_path,
        raw_manifest_path.parent / "toolsets.jsonl",
        configuration["dataset"].get("index_cache_bytes", 67108864),
    ) as store:
        for label, (row, events) in examples.items():
            definitions = []
            for digest in (row["target_before_digest"], row["target_after_digest"]):
                status, _, tool = store.lookup(digest, row["tool_name"])
                definitions.append(tool if status == "present" else None)
            changed = []
            if all(value is not None for value in definitions):
                before, after = definitions
                for key in ("description", "inputSchema", "outputSchema"):
                    old = json.dumps(
                        {key: before[key]} if key in before else {},
                        sort_keys=True,
                        ensure_ascii=False,
                    )
                    new = json.dumps(
                        {key: after[key]} if key in after else {},
                        sort_keys=True,
                        ensure_ascii=False,
                    )
                    if old != new:
                        if (
                            key == "description"
                            and isinstance(before.get(key), str)
                            and isinstance(after.get(key), str)
                        ):
                            changed.append(
                                f"description "
                                f"({len(before[key])}→{len(after[key])} "
                                f"characters)"
                            )
                        else:
                            changed.append(key)
            target = (
                row["target_change_id"]
                if row["target_change_id"] is not None
                else "unresolved"
            )
            lines.append(
                f"| {label} | `{_safe(row['server_id'])}` / "
                f"`{_safe(row['tool_name'])}` | {target} / "
                f"{row['target_timestamp'] or 'unknown'} | {row['source_type']} "
                f"| {row['max_eligible_k']} | "
                f"{', '.join(changed) or 'unresolved or unchanged'} |"
            )
            lines.append(
                f"| ↳ refs | before: `{_safe(row['target_before_digest'])}` | "
                f"after: `{_safe(row['target_after_digest'])}` | | | |"
            )
            if row["source_type"] in {"npm", "pypi"}:
                versions = _safe(row["target_recorded_versions_json"])
                lines.append(
                    f"| ↳ recorded versions | `{versions}` "
                    "| Missing and null values are not inferred | | | |"
                )
            lines.append(
                f"| ↳ counts | states {row['observed_state_count']:,}; "
                f"known definitions {row['known_distinct_definitions']:,} | "
                f"modifications {row['recorded_modifications']:,} | "
                f"reversions {row['observed_reversions']:,} | | |"
            )
            decisions = json.loads(row["windows_json"])
            lines.append(
                "| ↳ decisions | "
                + " | ".join(
                    f"k={k}: "
                    + (
                        "eligible"
                        if decisions[str(k)]["eligible"]
                        else _safe(decisions[str(k)]["reason"])
                    )
                    for k in (2, 4)
                )
                + " | | | |"
            )
            if row["max_eligible_k"] >= 2:
                k = min(row["max_eligible_k"], 10)
                states = json.loads(row["windows_json"])[str(k)]["states"]
                times_by_id = {
                    event["change_id"]: event["observed_at"] for event in events
                }
                references = ", ".join(
                    f"{state['change_id']}@{times_by_id[state['change_id']]}:"
                    f"{state['side']}:{state['toolset_digest']}"
                    for state in states
                )
                lines.append(f"| ↳ ordered k={k} | `{_safe(references)}` | | | | |")
            if label == "recognized counter churn":
                counter_event = next(
                    event
                    for event in events
                    if event["revision_kind"] == "trivial_tool_counter"
                )
                lines.append(
                    f"| ↳ counter event | change {counter_event['change_id']} "
                    f"at {counter_event['observed_at']} | "
                    f"`{_safe(counter_event['before_digest'])}` → "
                    f"`{_safe(counter_event['after_digest'])}` | | | |"
                )
    for label in sorted(set(criteria) - set(examples)):
        lines.append(f"| {label} | Not found by this mechanical selector | | | | |")
    lines.extend(
        [
            "",
            "The full selected state references and target before/after "
            "digests are retained in `tool_eligibility.parquet`; reconstructed "
            "events are in the histories Parquet file. Missing example "
            "categories indicate no matching category was found by the "
            "mechanical selection, not proof that none exists.",
            "",
            "## Research feasibility and limitations",
            "",
            "The distribution and leakage groups quantify structural "
            "availability, but they do not establish the number of independent "
            "labeled examples. Final sample requirements, publisher caps and "
            "maximum experimental k remain owner decisions. The configured "
            f"minimum cluster threshold is "
            f"{minimum_clusters if minimum_clusters is not None else 'unset'}. "
            "Numeric-description "
            "template grouping is a conservative similarity proxy and can "
            "group unrelated tools. Publisher/repository relationships and "
            "more general template similarity require further review.",
            "",
            "The observation period is short and left-censored; updates "
            "between polls may be missed. Tool renames are not linked. Package "
            "launch compatibility and historical source type may be uncertain. "
            "Extras linkage is limited to exact recorded timestamp matches, "
            "and scanner and classifier coverage are not equivalent to ground "
            "truth. Optional-field absence is not a capability assertion. "
            "Description language was not reliably determined and is unknown. "
            "Several Step 08 acceptance items require additional validation "
            "and independent review before this report can be treated as "
            "final.",
            "",
        ]
    )
    with output_path.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
    return {
        "candidate_tools": total,
        "recorded_modifications": modifications,
        "examples": len(examples),
        "flapping_histories": flapping,
    }
