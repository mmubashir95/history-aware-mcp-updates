import csv
import json

import pyarrow as pa
import pyarrow.parquet as pq

from mcp_history_security.data.histor.statistics import (
    enrich_distribution_coverage,
    feasibility_status,
    simulate_selection,
    summarize,
)


def test_distribution_and_funnel_keep_counting_units(tmp_path) -> None:
    assessments = tmp_path / "assessments.parquet"
    clusters = tmp_path / "clusters.parquet"
    records = []
    for server, k in [("s1", 2), ("s2", 3)]:
        windows = {
            str(n): {
                "eligible": n <= k,
                "reason": None if n <= k else "insufficient_history",
            }
            for n in range(2, 21)
        }
        records.append(
            {
                "server_id": server,
                "tool_name": "t",
                "source_type": "remote",
                "publisher_name_prefix": "p",
                "repository": "repo",
                "max_eligible_k": k,
                "windows_json": json.dumps(windows),
            }
        )
    pq.write_table(pa.Table.from_pylist(records), assessments)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"server_id": "s1", "tool_name": "t", "cluster_id": "c"},
                {"server_id": "s2", "tool_name": "t", "cluster_id": "c"},
            ]
        ),
        clusters,
    )
    result = summarize(assessments, clusters, tmp_path)
    assert result["candidate_tools"] == 2
    with (tmp_path / "history_length_distribution.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    row = next(
        row
        for row in rows
        if row["source_type"] == "all" and row["history_length"] == "2"
    )
    assert row["cumulative_eligible_count"] == "2"
    assert row["unique_leakage_clusters"] == "1"
    with (tmp_path / "eligibility_funnel.csv").open() as stream:
        funnel = list(csv.DictReader(stream))
    structural = [
        row
        for row in funnel
        if row["source_type"] == "all" and row["stage_id"] == "nested_history"
    ]
    assert structural[0]["input_population"] == "2"
    assert structural[1]["input_population"] == structural[0]["remaining_population"]
    deduplicated = next(
        row
        for row in funnel
        if row["source_type"] == "all"
        and row["stage_id"] == "simulated_dedup"
        and row["history_length"] == "2"
    )
    assert deduplicated["input_population"] == "2"
    assert deduplicated["remaining_population"] == "1"
    scenarios = [{"name": "dedup", "server_cap": 1, "publisher_cap": 1}]
    simulated = simulate_selection(assessments, clusters, scenarios, [2])
    assert simulated[0]["eligible_cluster_representatives"] == 1
    assert simulated[0]["selected"] == 1
    assert simulated[0]["distinct_servers"] == 1
    assert simulated[0]["distinct_publisher_name_prefixes"] == 1
    assert simulated[0]["distinct_repository_references"] == 1
    assert simulated[0]["missing_repository_selected"] == 0


def test_feasibility_does_not_invent_minimum() -> None:
    assert feasibility_status(10, None) == "threshold_not_set"
    assert feasibility_status(10, 10) == "meets_threshold"
    assert feasibility_status(9, 10) == "below_threshold"


def test_coverage_counts_unknown_annotation_separately(tmp_path) -> None:
    distribution = tmp_path / "distribution.csv"
    distribution.write_text(
        "source_type,history_length,unique_leakage_clusters\nall,2,1\n",
        encoding="utf-8",
    )
    states = [{"change_id": 1, "side": "before"}, {"change_id": 1, "side": "after"}]
    row = {
        "source_type": "remote",
        "max_eligible_k": 2,
        "selected_scanner_states_json": json.dumps(
            [dict(x, coverage="scanned") for x in states]
        ),
        "selected_annotation_states_json": json.dumps(
            [
                dict(states[0], annotation_status="unknown"),
                dict(states[1], annotation_status="present"),
            ]
        ),
        "selected_classification_coverage_json": json.dumps(
            [dict(x, coverage="unavailable") for x in states]
        ),
        "selected_launch_states_json": json.dumps(
            [dict(x, compatibility="not_applicable") for x in states]
        ),
    }
    table = tmp_path / "tools.parquet"
    output = tmp_path / "enriched.csv"
    pq.write_table(pa.Table.from_pylist([row]), table)
    enrich_distribution_coverage(distribution, table, output)
    with output.open() as stream:
        result = list(csv.DictReader(stream))[0]
    assert result["scanner_complete_windows"] == "1"
    assert result["annotation_complete_windows"] == "0"
    assert result["classification_complete_windows"] == "0"
