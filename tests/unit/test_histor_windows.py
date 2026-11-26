from mcp_history_security.data.histor.windows import assess_windows


def event(identifier, before, after, kind="substantive_uncertain", issues=None):
    return {
        "change_id": identifier,
        "before_digest": before,
        "after_digest": after,
        "before_hash": before,
        "after_hash": after,
        "recorded_modification": True,
        "revision_kind": kind,
        "issues": issues or [],
    }


def test_windows_preserve_actual_predecessor_and_substantive_context() -> None:
    history = {
        "events": [
            event(1, "a", "b"),
            event(2, "b", "c", "trivial_tool_counter"),
            event(3, "c", "d"),
        ]
    }
    result = assess_windows(history, 5)
    windows = result["windows"]
    assert [s["definition_hash"] for s in windows["3"]["states"]] == ["b", "c", "d"]
    assert [s["definition_hash"] for s in windows["4"]["states"]] == [
        "a",
        "b",
        "c",
        "d",
    ]
    assert not windows["5"]["eligible"]


def test_latest_unresolved_target_is_not_replaced() -> None:
    history = {
        "events": [
            event(1, "a", "b"),
            event(2, "b", None, "unknown", ["unresolved_state"]),
        ]
    }
    result = assess_windows(history, 3)
    assert result["target_change_id"] == 2
    assert not result["windows"]["2"]["eligible"]


def test_latest_contradictory_modification_is_not_replaced() -> None:
    history = {
        "events": [
            event(1, "a", "b"),
            event(2, "b", "b", "unchanged", ["summary_definition_mismatch"]),
        ]
    }
    result = assess_windows(history, 2)
    assert result["target_change_id"] == 2
    assert not result["windows"]["2"]["eligible"]


def test_gap_before_target_does_not_invalidate_target_pair() -> None:
    history = {
        "events": [
            event(1, "a", "b"),
            event(2, "x", "y", issues=["server_chain_break_before"]),
        ]
    }
    result = assess_windows(history, 3)
    assert result["windows"]["2"]["eligible"]
    assert result["windows"]["3"]["reason"] == "server_chain_break"


def test_context_excludes_later_trivial_observations() -> None:
    history = {
        "events": [event(1, "a", "b"), event(2, "b", "c", "trivial_tool_counter")]
    }
    result = assess_windows(history, 2)
    assert result["target_change_id"] == 1
    assert [state["definition_hash"] for state in result["windows"]["2"]["states"]] == [
        "a",
        "b",
    ]


def test_timestamp_ambiguity_and_different_launch_block_pair() -> None:
    for issue in ("same_timestamp_ambiguity", "launch_configuration_changed"):
        result = assess_windows({"events": [event(1, "a", "b", issues=[issue])]}, 2)
        assert not result["windows"]["2"]["eligible"]
        assert issue in result["windows"]["2"]["reason"]
