import json

import pyarrow as pa
import pyarrow.parquet as pq

from mcp_history_security.data.histor.clusters import build_clusters
from mcp_history_security.data.histor.index import build_definition_index
from mcp_history_security.data.histor.sources import definition_hash


def test_counter_templates_group_without_removing_members(tmp_path) -> None:
    index = tmp_path / "index.sqlite"
    changes = tmp_path / "changes.jsonl"
    toolsets = tmp_path / "toolsets.jsonl"
    change = {
        "id": 1,
        "serverId": "s",
        "observedAt": "time",
        "fromToolSetDigest": "a",
        "toToolSetDigest": "b",
        "summaryJson": json.dumps({"modified": [{"tool": "tool"}]}),
    }
    changes.write_text(json.dumps(change) + "\n", encoding="utf-8")
    toolsets.write_text(
        "\n".join(
            json.dumps(
                {
                    "digest": digest,
                    "toolsJson": json.dumps(
                        [{"name": "tool", "description": description}]
                    ),
                }
            )
            for digest, description in [
                ("a", "Offers 10 tools"),
                ("b", "Offers 11 tools"),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    build_definition_index(changes, toolsets, index)
    records = []
    for server, digest, description in [
        ("s1", "a", "Offers 10 tools"),
        ("s2", "b", "Offers 11 tools"),
    ]:
        state = {
            "toolset_digest": digest,
            "definition_hash": definition_hash(
                {"name": "tool", "description": description}
            ),
        }
        records.append(
            {
                "server_id": server,
                "tool_name": "tool",
                "max_eligible_k": 2,
                "cluster_id": server,
                "windows_json": json.dumps({"2": {"states": [state]}}),
            }
        )
    assessments = tmp_path / "assessments.parquet"
    output = tmp_path / "clusters.parquet"
    pq.write_table(pa.Table.from_pylist(records), assessments)
    result = build_clusters(assessments, index, toolsets, output)
    rows = pq.read_table(output).to_pylist()
    assert result["clusters"] == 1
    assert len(rows) == 2
    assert sum(row["representative"] for row in rows) == 1
    assert all(row["cluster_size"] == 2 for row in rows)
