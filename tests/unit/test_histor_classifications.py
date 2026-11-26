import json

import pyarrow as pa
import pyarrow.parquet as pq

from mcp_history_security.data.histor.classifications import (
    load_classifications,
    write_classification_coverage,
)


def test_classification_records_availability_not_labels(tmp_path) -> None:
    path = tmp_path / "classifications.jsonl"
    path.write_text(
        json.dumps(
            {
                "toolSetDigest": "d",
                "model": "model",
                "updatedAt": "time",
                "verdictJson": json.dumps({"findings": []}),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = load_classifications(path)
    assert result["d"][0]["finding_count"] == 0
    assert "label" not in result["d"][0]


def test_partial_classification_is_not_full_toolset_coverage(tmp_path) -> None:
    source = tmp_path / "classifications.jsonl"
    source.write_text(
        json.dumps(
            {
                "toolSetDigest": "d",
                "model": "m",
                "verdictJson": json.dumps(
                    {
                        "findings": [],
                        "checkedTools": 1,
                        "toolCount": 2,
                        "truncatedTools": 1,
                    }
                ),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assessments = tmp_path / "assessments.parquet"
    states = [
        {"change_id": 1, "side": "before", "toolset_digest": "d"},
        {"change_id": 1, "side": "after", "toolset_digest": "missing"},
    ]
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "server_id": "s",
                    "tool_name": "t",
                    "max_eligible_k": 2,
                    "windows_json": json.dumps({"2": {"states": states}}),
                }
            ]
        ),
        assessments,
    )
    output = tmp_path / "coverage.parquet"
    write_classification_coverage(assessments, source, output)
    assert [row["coverage"] for row in pq.read_table(output).to_pylist()] == [
        "available_partial_or_unknown",
        "unavailable",
    ]
