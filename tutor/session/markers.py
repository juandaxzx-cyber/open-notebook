"""Task-boundary markers (PR-E2 part a).

The session prompt instructs the tutor to open every NEW task with a line
``[[TASK: short label]]``. The engine parses tutor replies with
:func:`parse_task_marker`: the raw reply (marker included) goes into the
transcript so the model keeps seeing its own boundaries in the history,
while the cleaned text is what the learner-facing API returns.

If the model never emits a marker, nothing breaks: the session stays on the
implicit task 0 and behaves exactly like pre-E2 sessions.
"""

import re

_MARKER = re.compile(r"\[\[\s*TASK\s*:\s*(.+?)\s*\]\]", re.IGNORECASE)


def parse_task_marker(reply: str) -> tuple[str | None, str]:
    """Extract the first task marker from a tutor reply.

    Returns ``(label, cleaned_reply)``; ``label`` is ``None`` when the reply
    contains no marker. Only the first marker counts (one task per turn);
    any extra markers are stripped but ignored.
    """
    match = _MARKER.search(reply)
    if match is None:
        return None, reply
    label = match.group(1).strip()
    cleaned = _MARKER.sub("", reply)
    # collapse the whitespace holes left by stripped markers
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return label or None, cleaned
