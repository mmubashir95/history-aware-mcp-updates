from mcp_history_security.data.histor.output import _history_counts


def test_history_counts_reversions_without_crossing_unknown_states() -> None:
    events = [
        {
            "before_hash": "a",
            "after_hash": "b",
            "recorded_modification": True,
            "issues": [],
        },
        {
            "before_hash": "b",
            "after_hash": "a",
            "recorded_modification": True,
            "issues": [],
        },
        {
            "before_hash": "x",
            "after_hash": "b",
            "recorded_modification": True,
            "issues": ["server_chain_break_before"],
        },
    ]
    result = _history_counts(events)
    assert result["observed_reversions"] == 1
    assert result["known_distinct_definitions"] == 3
    assert result["unknown_state_count"] == 1


def test_configuration_change_does_not_create_a_reversion() -> None:
    events = [
        {
            "before_hash": "a",
            "after_hash": "b",
            "recorded_modification": True,
            "revision_kind": "substantive_uncertain",
            "issues": [],
        },
        {
            "before_hash": "b",
            "after_hash": "a",
            "recorded_modification": True,
            "revision_kind": "substantive_uncertain",
            "issues": ["launch_configuration_changed"],
        },
    ]
    result = _history_counts(events)
    assert result["observed_reversions"] == 0
    assert result["unknown_state_count"] == 1
