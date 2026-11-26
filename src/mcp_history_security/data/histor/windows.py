"""Select traceable nested windows around a recorded substantive target."""

from __future__ import annotations


def assess_windows(history: dict, max_k: int) -> dict:
    """Evaluate each requested length without bridging unknown transitions."""
    if max_k < 2:
        raise ValueError("max_k must be at least 2")
    events = history["events"]
    # A contradictory summary is still a candidate target: skipping it could
    # silently substitute an older, apparently complete update.
    targets = [
        index
        for index, event in enumerate(events)
        if event["recorded_modification"]
        and (
            event["revision_kind"] not in {"trivial_tool_counter", "unchanged"}
            or "summary_definition_mismatch" in event["issues"]
        )
    ]
    if not targets:
        return {
            "target_change_id": None,
            "windows": {
                str(k): {
                    "eligible": False,
                    "reason": "no_substantive_target",
                    "states": [],
                }
                for k in range(2, max_k + 1)
            },
        }
    target_index = targets[-1]
    target = events[target_index]
    # A break before this event affects earlier context, not a resolved
    # predecessor/target pair contained within the event itself.
    blocked = set(target["issues"]) - {"server_chain_break_before"}
    if target["revision_kind"] == "unknown":
        blocked.add("unknown_target")
    if blocked:
        reason = ",".join(sorted(blocked))
        return {
            "target_change_id": target["change_id"],
            "windows": {
                str(k): {"eligible": False, "reason": reason, "states": []}
                for k in range(2, max_k + 1)
            },
        }

    def state(event: dict, side: str) -> dict:
        return {
            "toolset_digest": event[f"{side}_digest"],
            "definition_hash": event[f"{side}_hash"],
            "change_id": event["change_id"],
            "side": side,
        }

    # Build backward from the target, retaining its actual predecessor even
    # when an earlier edit was classified as trivial. Reverse for output.
    states = [state(target, "after"), state(target, "before")]
    current_hash = target["before_hash"]
    windows = {
        "2": {"eligible": True, "reason": None, "states": list(reversed(states))}
    }
    stop_reason = "insufficient_history"
    for index in range(target_index - 1, -1, -1):
        if len(states) >= max_k:
            break
        later = events[index + 1]
        event = events[index]
        # The break belongs to the later event: crossing it would claim a
        # connection between toolsets that the source did not establish.
        if "server_chain_break_before" in later["issues"]:
            stop_reason = "server_chain_break"
            break
        issues = set(event["issues"]) - {"server_chain_break_before"}
        if issues or event["after_hash"] != current_hash:
            stop_reason = (
                ",".join(sorted(issues)) if issues else "definition_chain_break"
            )
            break
        if event["revision_kind"] == "substantive_uncertain":
            # The event's after-state may precede trivial edits immediately
            # before the target; retain it before considering the older state.
            if event["after_hash"] != states[-1]["definition_hash"]:
                states.append(state(event, "after"))
            if event["before_hash"] != states[-1]["definition_hash"]:
                states.append(state(event, "before"))
        current_hash = event["before_hash"]
        # Each longer window must end in exactly the same shorter suffix.
        for k in range(3, min(max_k, len(states)) + 1):
            windows.setdefault(
                str(k),
                {
                    "eligible": True,
                    "reason": None,
                    "states": list(reversed(states[:k])),
                },
            )
    for k in range(2, max_k + 1):
        windows.setdefault(
            str(k), {"eligible": False, "reason": stop_reason, "states": []}
        )
    return {"target_change_id": target["change_id"], "windows": windows}
