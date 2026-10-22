"""
music_bridge.py — AppleScript bridge to Music.app.

A single osascript call per poll returns the track, position and player state,
so we spawn one process per tick instead of several.
"""
from __future__ import annotations

import subprocess

_POLL_SCRIPT = """
tell application "Music"
    set ps to player state
    if ps is stopped then return "stopped"
    set t to current track
    set isPlaying to "false"
    if ps is playing then set isPlaying to "true"
    return (artist of t) & "|||" & (name of t) & "|||" & (album of t) & "|||" & ((duration of t) as string) & "|||" & ((player position) as string) & "|||" & isPlaying
end tell
"""

_LYRICS_SCRIPT = """
tell application "Music"
    if player state is stopped then return ""
    try
        set lyr to lyrics of current track
        if lyr is missing value then return ""
        return lyr
    on error
        return ""
    end try
end tell
"""


def _run_applescript(script: str) -> str:
    """Run an AppleScript and return its stdout, or '' on any failure."""
    try:
        result = subprocess.run(["osascript", "-e", script],
                                capture_output=True, text=True, timeout=3)
        return result.stdout.strip()
    except Exception:
        return ""


def _to_float(s: str) -> float:
    # AppleScript formats numbers with the locale's decimal separator.
    return float(s.strip().replace(",", "."))


def poll_player() -> dict | None:
    """{artist, title, album, duration, position, playing}, or None if nothing is playing."""
    parts = _run_applescript(_POLL_SCRIPT).split("|||")
    if len(parts) != 6:
        return None
    artist, title, album, duration, position, playing = parts
    try:
        return {
            "artist":   artist.strip(),
            "title":    title.strip(),
            "album":    album.strip(),
            "duration": _to_float(duration),
            "position": _to_float(position),
            "playing":  playing.strip().lower() == "true",
        }
    except ValueError:
        return None


def is_music_running() -> bool:
    out = _run_applescript('tell application "System Events" to (name of processes) contains "Music"')
    return out.lower() == "true"


def get_plain_lyrics() -> str | None:
    """Plain-text lyrics Apple Music stores for the current track, if any."""
    return _run_applescript(_LYRICS_SCRIPT) or None


def make_estimated_lyrics(plain_lyrics: str, duration: float) -> list[tuple[float, str]]:
    """Spread plain lyric lines evenly between 3% and 92% of the song (best-effort sync)."""
    lines = [ln.strip() for ln in plain_lyrics.splitlines() if ln.strip()]
    if not lines or duration <= 0:
        return []
    start = duration * 0.03
    interval = (duration * 0.92 - start) / len(lines)
    return [(round(start + i * interval, 2), line) for i, line in enumerate(lines)]
