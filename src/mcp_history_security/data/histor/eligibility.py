"""Conservative structural checks for recorded tool histories."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Transition:
    """A recorded transition; missing references do not establish continuity."""

    before: str | None
    after: str | None
    substantive: bool
    resolved: bool = True


def eligible_window(transitions: tuple[Transition, ...], k: int) -> bool:
    """Check a window ending at the latest recorded substantive transition.

    Earlier context is chosen from substantive transitions, while the target's
    actual immediate predecessor is retained even after trivial edits.
    """
    return select_window(transitions, k) is not None


def select_window(
    transitions: tuple[Transition, ...], k: int
) -> tuple[str, ...] | None:
    """Select nested state references, or return None when a window is unresolved."""
    if k < 2:
        raise ValueError("k must be at least 2")
    targets = [i for i, transition in enumerate(transitions) if transition.substantive]
    if not targets:
        return None
    target = targets[-1]
    selected = transitions[target]
    if not selected.resolved or not selected.before or not selected.after:
        return None
    states = [selected.after, selected.before]
    current = selected.before
    for transition in reversed(transitions[:target]):
        if len(states) >= k:
            break
        if (
            not transition.resolved
            or not transition.before
            or not transition.after
            or transition.after != current
        ):
            return None
        if transition.substantive and transition.after != states[-1]:
            states.append(transition.after)
            if len(states) >= k:
                break
        current = transition.before
        if transition.substantive and current != states[-1]:
            states.append(current)
    return tuple(reversed(states)) if len(states) == k else None
