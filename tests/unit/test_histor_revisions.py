from mcp_history_security.data.histor.revisions import revision_kind


def test_counter_is_narrowly_classified() -> None:
    assert (
        revision_kind(
            {"description": "Offers 12 tools."}, {"description": "Offers 13 tools."}
        )
        == "trivial_tool_counter"
    )
    assert (
        revision_kind(
            {"description": "You may delete 12 tools."},
            {"description": "You may delete 13 tools."},
        )
        == "substantive_uncertain"
    )
    assert (
        revision_kind(
            {"description": "Limit 12 requests."}, {"description": "Limit 13 requests."}
        )
        == "substantive_uncertain"
    )


def test_schema_or_hidden_change_is_not_trivial() -> None:
    assert (
        revision_kind(
            {"description": "12 tools", "inputSchema": {}},
            {"description": "13 tools", "inputSchema": {"type": "object"}},
        )
        == "substantive_uncertain"
    )


def test_boolean_and_number_are_distinct_json_values() -> None:
    assert (
        revision_kind(
            {"description": "12 tools", "inputSchema": {"default": 1}},
            {"description": "13 tools", "inputSchema": {"default": True}},
        )
        == "substantive_uncertain"
    )
    assert (
        revision_kind(
            {"description": "12 tools\u200b"}, {"description": "13 tools\u200b"}
        )
        == "substantive_uncertain"
    )
