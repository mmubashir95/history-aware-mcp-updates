"""Mechanical quality indicators for recorded individual-tool histories."""


def flapping_indicator(events: list[dict]) -> bool:
    """Identify A→B→A→B→A without crossing an unresolved transition."""
    states = []
    invalid = {
        "server_chain_break_before",
        "unresolved_state",
        "same_timestamp_ambiguity",
        "names_only",
        "summary_definition_mismatch",
    }
    for event in events:
        if invalid.intersection(event["issues"]):
            states = []
            continue
        for value in (event["before_hash"], event["after_hash"]):
            if value and (not states or states[-1] != value):
                states.append(value)
                if (
                    len(states) >= 5
                    and states[-5] == states[-3] == states[-1]
                    and states[-4] == states[-2]
                    and states[-5] != states[-4]
                ):
                    return True
    return False
