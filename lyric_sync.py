"""lyric_sync.py — Find the current lyric line for a playback position."""
from __future__ import annotations

import bisect


def find_current_line(lyrics: list[tuple[float, str]], position: float) -> int:
    """Index of the last line that has started by `position`, or -1 if none has."""
    return bisect.bisect_right([ts for ts, _ in lyrics], position) - 1
