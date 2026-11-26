from mcp_history_security.data.histor.fields import definition_hidden, field_status


def test_optional_fields_keep_absent_null_and_empty_separate() -> None:
    assert field_status({}, "field") == "absent"
    assert field_status({"field": None}, "field") == "null"
    assert field_status({"field": {}}, "field") == "empty"
    assert field_status({"field": False}, "field") == "present"


def test_hidden_unicode_is_detected_in_nested_schema() -> None:
    assert definition_hidden({"inputSchema": {"properties": {"x\u200b": {}}}})
    assert not definition_hidden({"description": "normal"})
