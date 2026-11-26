"""Conservative mechanical classification of individual tool definitions."""

from __future__ import annotations

import re
import unicodedata

from .sources import definition_hash

_TOOL_COUNTER = re.compile(r"\b\d+(?=\s+tools\b)", re.IGNORECASE)
_STANDALONE_COUNTER = re.compile(
    r"\s*(?:offers|provides|contains)\s+\d+\s+tools\.?\s*", re.IGNORECASE
)


def hidden_characters(value: str) -> bool:
    """Identify format, private-use, surrogate and selected spacing characters."""
    return any(
        unicodedata.category(char) in {"Cf", "Co", "Cs"} or char in {"\u00a0", "\u3000"}
        for char in value
    )


def revision_kind(
    before: dict, after: dict, *, same_content: bool | None = None
) -> str:
    """Return unchanged, trivial_tool_counter, or substantive_uncertain.

    Only a standalone statement such as "Offers 12 tools." is recognized;
    all other fields and all nonnumeric description text must be identical.
    All unrecognized changes remain substantive, including whitespace changes.
    """
    if same_content is None:
        same_content = definition_hash(before) == definition_hash(after)
    if same_content:
        return "unchanged"
    old_description = before.get("description")
    new_description = after.get("description")
    if not isinstance(old_description, str) or not isinstance(new_description, str):
        return "substantive_uncertain"
    if hidden_characters(old_description) or hidden_characters(new_description):
        return "substantive_uncertain"
    # A number in a longer description may be a security limit; only the
    # narrowly specified standalone counter can be collapsed as trivial.
    if not _STANDALONE_COUNTER.fullmatch(
        old_description
    ) or not _STANDALONE_COUNTER.fullmatch(new_description):
        return "substantive_uncertain"
    if definition_hash(
        {k: v for k, v in before.items() if k != "description"}
    ) != definition_hash({k: v for k, v in after.items() if k != "description"}):
        return "substantive_uncertain"
    normalized_old = _TOOL_COUNTER.sub("<tool-count>", old_description)
    normalized_new = _TOOL_COUNTER.sub("<tool-count>", new_description)
    if normalized_old == normalized_new and normalized_old != old_description:
        return "trivial_tool_counter"
    return "substantive_uncertain"
