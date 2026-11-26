from mcp_history_security.data.histor.quality import flapping_indicator
from mcp_history_security.data.histor.report import (
    _safe,
    _summary_funnel,
    _target_hidden_presence,
)


def test_flapping_does_not_bridge_unknown_state() -> None:
    def event(before, after, issues=None):
        return {"before_hash": before, "after_hash": after, "issues": issues or []}

    assert flapping_indicator(
        [event("a", "b"), event("b", "a"), event("a", "b"), event("b", "a")]
    )
    assert not flapping_indicator(
        [
            event("a", "b"),
            event("b", "a"),
            event(None, "b", ["unresolved_state"]),
            event("b", "a"),
        ]
    )


def test_untrusted_identity_is_escaped_for_report() -> None:
    text = _safe("x|`<script>\n")
    assert "|" not in text
    assert "`" not in text
    assert "<script>" not in text


def test_report_funnel_separates_structural_and_deduplication_stages(tmp_path) -> None:
    path = tmp_path / "funnel.csv"
    path.write_text(
        "stage_id,source_type,history_length,input_population,remaining_population\n"
        "nested_history,all,2,10,8\n"
        "simulated_dedup,all,2,8,6\n"
        "window,all,2,10,8\n"
        "nested_history,npm,2,4,3\n"
        "nested_history,all,11,2,1\n",
        encoding="utf-8",
    )
    result = _summary_funnel(path)
    assert [(row["stage_id"], row["input_population"]) for row in result] == [
        ("nested_history", "10"),
        ("simulated_dedup", "8"),
    ]


def test_hidden_presence_compares_actual_final_pair() -> None:
    def states(*values):
        return [{"hidden_characters": value} for value in values]

    assert _target_hidden_presence(states(True, False, True)) == "introduced"
    assert _target_hidden_presence(states(True, False)) == "removed"
    assert _target_hidden_presence(states(True, True)) == "present_both"
    assert _target_hidden_presence(states(False, False)) is None
    assert _target_hidden_presence(states(True)) is None
