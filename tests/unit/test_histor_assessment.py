from copy import deepcopy

from mcp_history_security.data.histor.assessment import assess_history


def test_scanner_findings_do_not_change_structural_decisions() -> None:
    history = {
        "server_id": "s",
        "tool_name": "t",
        "events": [
            {
                "change_id": 1,
                "observed_at": "2026-01-01T00:00:00Z",
                "before_digest": "a",
                "after_digest": "b",
                "before_hash": "ha",
                "after_hash": "hb",
                "recorded_modification": True,
                "revision_kind": "substantive_uncertain",
                "issues": [],
            }
        ],
    }
    clean = {"a": {}, "b": {}}
    finding = {
        "identity": ("C", "description"),
        "span_hash": "f",
        "tier": "block",
        "code": "C",
    }
    flagged = {"a": {}, "b": {"t": [finding]}}
    first = assess_history(deepcopy(history), {"source_type": "remote"}, {}, clean)
    second = assess_history(deepcopy(history), {"source_type": "remote"}, {}, flagged)
    assert first["windows_json"] == second["windows_json"]
    assert first["target_scanner_json"] != second["target_scanner_json"]
