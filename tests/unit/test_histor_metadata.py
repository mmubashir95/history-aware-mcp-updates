from mcp_history_security.data.histor.metadata import launch_compatibility


def test_launch_compatibility_keeps_missing_and_mixed_unknown() -> None:
    assert launch_compatibility({"a"}, {"a"}) == "matching"
    assert launch_compatibility({"a"}, {"b"}) == "different"
    assert launch_compatibility({None}, {"a"}) == "unknown"
    assert launch_compatibility({"a", "b"}, {"b"}) == "unknown"
    assert launch_compatibility(set(), {"b"}) == "unknown"
