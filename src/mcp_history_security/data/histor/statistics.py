"""Summarize candidate-level decisions with explicit counting units."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq


def feasibility_status(cluster_count: int, minimum: int | None) -> str:
    """Apply an explicitly configured threshold without inventing one."""
    if cluster_count < 0:
        raise ValueError("cluster count cannot be negative")
    if minimum is None:
        return "threshold_not_set"
    if type(minimum) is not int or minimum <= 0:
        raise ValueError("minimum must be positive")
    return "meets_threshold" if cluster_count >= minimum else "below_threshold"


def summarize(assessments_path: Path, clusters_path: Path, output_dir: Path) -> dict:
    """Write non-destructive provisional history distributions and window funnel."""
    distribution_path = output_dir / "history_length_distribution.csv"
    funnel_path = output_dir / "eligibility_funnel.csv"
    exclusions_path = output_dir / "exclusion_reasons.csv"
    for path in (distribution_path, funnel_path, exclusions_path):
        if path.exists():
            raise FileExistsError(f"refusing to overwrite output: {path}")
    clusters = {}
    for row in pq.read_table(clusters_path).to_pylist():
        key = (row["server_id"], row["tool_name"])
        if key in clusters:
            raise ValueError("duplicate cluster identity")
        clusters[key] = row["cluster_id"]
    populations = Counter()
    exact = Counter()
    counts = Counter()
    servers = defaultdict(set)
    publishers = defaultdict(set)
    groups = defaultdict(set)
    reasons = Counter()
    evaluated = Counter()
    observed_ids = set()
    max_observed = 0
    columns = [
        "server_id",
        "tool_name",
        "source_type",
        "publisher_name_prefix",
        "max_eligible_k",
        "windows_json",
    ]
    for batch in pq.ParquetFile(assessments_path).iter_batches(columns=columns):
        for row in batch.to_pylist():
            identity = (row["server_id"], row["tool_name"])
            if identity in observed_ids or identity not in clusters:
                raise ValueError("duplicate or missing candidate identity")
            observed_ids.add(identity)
            max_k = row["max_eligible_k"]
            max_observed = max(max_observed, max_k)
            windows = json.loads(row["windows_json"])
            for source in ("all", row["source_type"]):
                populations[source] += 1
                # Exact counts group by maximum eligible k; cumulative counts
                # include the tool once for every eligible shorter window.
                exact[(source, max_k)] += 1
                for k in range(2, max_k + 1):
                    key = (source, k)
                    counts[key] += 1
                    servers[key].add(row["server_id"])
                    if row["publisher_name_prefix"] is not None:
                        publishers[key].add(row["publisher_name_prefix"])
                    groups[key].add(clusters[identity])
                for k, decision in windows.items():
                    evaluated[(source, int(k))] += 1
                    if not decision["eligible"]:
                        for reason in decision["reason"].split(","):
                            reasons[(source, int(k), reason)] += 1
    if len(observed_ids) != len(clusters):
        raise ValueError("cluster and assessment populations differ")
    # A length beyond a candidate's evaluation bound is recorded separately
    # from an observed broken or unresolved transition.
    max_reported = max(20, max_observed)
    for source, population in populations.items():
        for k in range(2, max_reported + 1):
            not_evaluated = population - evaluated[(source, k)]
            if not_evaluated:
                reasons[(source, k, "beyond_history_bound")] += not_evaluated
    with distribution_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "source_type",
                "history_length",
                "exact_max_eligible_count",
                "cumulative_eligible_count",
                "unique_leakage_clusters",
                "unique_servers",
                "unique_publisher_name_prefixes",
            ]
        )
        for source in sorted(populations):
            for k in range(2, max_reported + 1):
                key = (source, k)
                writer.writerow(
                    [
                        source,
                        k,
                        exact[key],
                        counts[key],
                        len(groups[key]),
                        len(servers[key]),
                        len(publishers[key]),
                    ]
                )
    with funnel_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "stage_id",
                "stage_description",
                "source_type",
                "history_length",
                "input_population",
                "remaining_population",
                "excluded_population",
                "excluded_percent",
                "counting_unit",
                "counting_methodology",
            ]
        )
        for source in sorted(populations):
            previous = populations[source]
            for k in range(2, max_reported + 1):
                population = populations[source]
                remaining = counts[(source, k)]
                writer.writerow(
                    [
                        "window",
                        "structural window decision",
                        source,
                        k,
                        population,
                        remaining,
                        population - remaining,
                        100 * (population - remaining) / population,
                        "candidate tool identity",
                        "same primary target; overlapping exclusions "
                        "reported separately",
                    ]
                )
                if remaining > previous:
                    raise ValueError("nested eligible populations increased")
                writer.writerow(
                    [
                        "nested_history",
                        "additional context structural gate",
                        source,
                        k,
                        previous,
                        remaining,
                        previous - remaining,
                        100 * (previous - remaining) / previous if previous else 0,
                        "candidate tool identity",
                        "sequential nested windows; identical target",
                    ]
                )
                cluster_count = len(groups[(source, k)])
                writer.writerow(
                    [
                        "simulated_dedup",
                        "one representative per leakage cluster",
                        source,
                        k,
                        remaining,
                        cluster_count,
                        remaining - cluster_count,
                        100 * (remaining - cluster_count) / remaining
                        if remaining
                        else 0,
                        "candidate tool identity",
                        "simulation, not structural exclusion; "
                        "source groups can overlap",
                    ]
                )
                previous = remaining
    with exclusions_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["source_type", "history_length", "reason", "candidate_tools"])
        for (source, k, reason), count in sorted(reasons.items()):
            writer.writerow([source, k, reason, count])
    return {
        "candidate_tools": len(observed_ids),
        "max_eligible_k": max_observed,
        "exclusion_reasons": [
            {"source_type": source, "k": k, "reason": reason, "count": count}
            for (source, k, reason), count in sorted(reasons.items())
        ],
    }


def simulate_selection(
    assessments_path: Path,
    clusters_path: Path,
    scenarios: list[dict],
    lengths: list[int],
) -> list[dict]:
    """Select eligible cluster representatives before applying proposed caps."""
    clusters = {
        (row["server_id"], row["tool_name"]): row["cluster_id"]
        for row in pq.read_table(clusters_path).to_pylist()
    }
    records = pq.read_table(
        assessments_path,
        columns=[
            "server_id",
            "tool_name",
            "source_type",
            "publisher_name_prefix",
            "repository",
            "max_eligible_k",
        ],
    ).to_pylist()
    records.sort(key=lambda row: (row["server_id"], row["tool_name"]))
    output = []
    for k in lengths:
        if type(k) is not int or k < 2:
            raise ValueError("scenario history lengths must be integers >= 2")
        # Choose one deterministic representative per eligible cluster before
        # applying any proposed server or publisher concentration caps.
        representatives = []
        seen = set()
        for row in records:
            if row["max_eligible_k"] < k:
                continue
            cluster = clusters[(row["server_id"], row["tool_name"])]
            if cluster not in seen:
                representatives.append(row)
                seen.add(cluster)
        for scenario in scenarios:
            server_cap = scenario["server_cap"]
            publisher_cap = scenario["publisher_cap"]
            if any(
                value is not None and (type(value) is not int or value <= 0)
                for value in (server_cap, publisher_cap)
            ):
                raise ValueError("scenario caps must be positive integers or null")
            server_counts: Counter = Counter()
            publisher_counts: Counter = Counter()
            sources: Counter = Counter()
            repositories = set()
            unknown_publishers = 0
            unknown_repositories = 0
            for row in representatives:
                server = row["server_id"]
                publisher = row["publisher_name_prefix"]
                if server_cap is not None and server_counts[server] >= server_cap:
                    continue
                # Missing publisher metadata is not a single shared publisher;
                # leave it uncapped and report the missing count separately.
                if (
                    publisher is not None
                    and publisher_cap is not None
                    and publisher_counts[publisher] >= publisher_cap
                ):
                    continue
                server_counts[server] += 1
                if publisher is None:
                    unknown_publishers += 1
                else:
                    publisher_counts[publisher] += 1
                sources[row["source_type"]] += 1
                if row["repository"]:
                    repositories.add(row["repository"])
                else:
                    unknown_repositories += 1
            output.append(
                {
                    "scenario": scenario["name"],
                    "history_length": k,
                    "eligible_cluster_representatives": len(representatives),
                    "selected": sum(sources.values()),
                    "missing_publisher_selected": unknown_publishers,
                    "distinct_servers": len(server_counts),
                    "distinct_publisher_name_prefixes": len(publisher_counts),
                    "distinct_repository_references": len(repositories),
                    "missing_repository_selected": unknown_repositories,
                    "source_counts": dict(sources),
                    "server_cap": server_cap,
                    "publisher_cap": publisher_cap,
                }
            )
    return output


def write_scenarios(path: Path, rows: list[dict]) -> None:
    """Persist simulated selection results without overwriting previous runs."""
    with path.open("x", encoding="utf-8") as stream:
        json.dump(rows, stream, indent=2, sort_keys=True)
        stream.write("\n")


def enrich_distribution_coverage(
    distribution_path: Path, table_path: Path, output_path: Path
) -> dict[str, int]:
    """Add nested-window coverage counts without interpreting unknown as absent."""
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite distribution: {output_path}")
    coverage: Counter = Counter()
    candidate_count = 0
    columns = [
        "source_type",
        "max_eligible_k",
        "selected_scanner_states_json",
        "selected_annotation_states_json",
        "selected_classification_coverage_json",
        "selected_launch_states_json",
    ]
    for batch in pq.ParquetFile(table_path).iter_batches(columns=columns):
        for row in batch.to_pylist():
            candidate_count += 1
            length = row["max_eligible_k"]
            if length < 2:
                continue
            scanner = json.loads(row["selected_scanner_states_json"])
            annotations = json.loads(row["selected_annotation_states_json"])
            classifications = json.loads(row["selected_classification_coverage_json"])
            launches = json.loads(row["selected_launch_states_json"])
            if any(
                len(states) != length
                for states in (scanner, annotations, classifications, launches)
            ):
                raise ValueError("selected state coverage length does not match window")
            scan_complete = annotation_complete = classification_complete = True
            launch_uncertain = False
            for k in range(1, length + 1):
                refs = [
                    states[-k]
                    for states in (scanner, annotations, classifications, launches)
                ]
                if len({(ref["change_id"], ref["side"]) for ref in refs}) != 1:
                    raise ValueError("selected state coverage references do not align")
                scan_complete &= refs[0]["coverage"] == "scanned"
                annotation_complete &= refs[1]["annotation_status"] not in {
                    "unknown",
                    "unresolved_reference",
                    "malformed",
                }
                classification_complete &= (
                    refs[2]["coverage"] == "available_full_toolset"
                )
                launch_uncertain |= refs[3]["compatibility"] == "unknown"
                if k >= 2:
                    for source in ("all", row["source_type"]):
                        coverage[(source, k, "scanner")] += scan_complete
                        coverage[(source, k, "annotation")] += annotation_complete
                        coverage[(source, k, "classification")] += (
                            classification_complete
                        )
                        coverage[(source, k, "launch_uncertain")] += launch_uncertain
    with distribution_path.open(encoding="utf-8", newline="") as source_stream:
        reader = csv.DictReader(source_stream)
        if reader.fieldnames is None:
            raise ValueError("distribution has no header")
        fields = reader.fieldnames + [
            "representative_count",
            "sampling_scenario",
            "scanner_complete_windows",
            "annotation_complete_windows",
            "classification_complete_windows",
            "launch_uncertain_windows",
        ]
        with output_path.open("x", encoding="utf-8", newline="") as output_stream:
            writer = csv.DictWriter(output_stream, fieldnames=fields)
            writer.writeheader()
            for row in reader:
                source, k = row["source_type"], int(row["history_length"])
                row.update(
                    {
                        "representative_count": row["unique_leakage_clusters"],
                        "sampling_scenario": "structural_before_sampling",
                        "scanner_complete_windows": coverage[(source, k, "scanner")],
                        "annotation_complete_windows": coverage[
                            (source, k, "annotation")
                        ],
                        "classification_complete_windows": coverage[
                            (source, k, "classification")
                        ],
                        "launch_uncertain_windows": coverage[
                            (source, k, "launch_uncertain")
                        ],
                    }
                )
                writer.writerow(row)
    return {"candidate_tools": candidate_count}
