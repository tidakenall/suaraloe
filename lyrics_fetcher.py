"""
lyrics_fetcher.py — Fetch lyrics from LRClib.net, with a disk cache for synced results.

Lookup order, for both synced and plain lyrics:
  1. exact match on the original artist + title + album
  2. exact match on the cleaned artist + title (no album)
  3. search on the cleaned artist + title, keeping only results whose artist and
     title actually match, so a fuzzy hit for a different song is rejected
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import requests

CACHE_DIR = Path.home() / ".cache" / "apple-music-lyrics"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Bump when the matching logic changes so cached wrong-song hits get ignored.
CACHE_VERSION = "v2"
LRCLIB_BASE = "https://lrclib.net/api"

_LRC_LINE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")


# ------------------------------------------------------------------ #
#  Name matching                                                      #
# ------------------------------------------------------------------ #

def _clean_title(title: str) -> str:
    """Strip feat./remaster/single/version tags that break exact matching."""
    t = re.sub(r'\s*[\(\[](feat|ft|with|prod)\.?[^\)\]]*[\)\]]', '', title, flags=re.I)
    t = re.sub(r'\s*[\(\[](Remaster\w*|Deluxe|Single|Version|Radio Edit|Edit|Live)[^\)\]]*[\)\]]',
               '', t, flags=re.I)
    t = re.sub(r'\s+-\s+(Single|EP|Remaster\w*|Live)\s*$', '', t, flags=re.I)
    return t.strip()


def _clean_artist(artist: str) -> str:
    """Keep only the first credited artist."""
    return re.split(r'\s*[&,]\s*|\s+feat\.?\s+|\s+ft\.?\s+|\s+x\s+', artist, flags=re.I)[0].strip()


def _same(a: str, b: str) -> bool:
    """Loose match: equal, or one contains the other, ignoring case and punctuation."""
    a, b = (re.sub(r'[^a-z0-9]+', '', s.lower()) for s in (a, b))
    return bool(a and b) and (a in b or b in a)


# ------------------------------------------------------------------ #
#  Disk cache                                                         #
# ------------------------------------------------------------------ #

def _cache_path(artist: str, title: str) -> Path:
    key = hashlib.md5(f"{CACHE_VERSION}|{artist.lower()}|{title.lower()}".encode()).hexdigest()
    return CACHE_DIR / f"{key}.json"


def _load_cache(artist: str, title: str):
    """Cached lyrics ([] for a known miss), or None if never looked up."""
    try:
        return json.loads(_cache_path(artist, title).read_text())
    except (OSError, ValueError):
        return None


def _save_cache(artist: str, title: str, lyrics: list) -> None:
    try:
        _cache_path(artist, title).write_text(json.dumps(lyrics))
    except OSError:
        pass


# ------------------------------------------------------------------ #
#  LRClib                                                             #
# ------------------------------------------------------------------ #

def parse_lrc(lrc_text: str) -> list[tuple[float, str]]:
    """Parse LRC text into (seconds, line) pairs sorted by time."""
    lines = [(int(m) * 60 + float(s), text.strip())
             for m, s, text in _LRC_LINE.findall(lrc_text) if text.strip()]
    return sorted(lines, key=lambda x: x[0])


def _get(endpoint: str, params: dict):
    try:
        r = requests.get(f"{LRCLIB_BASE}/{endpoint}", params=params, timeout=6)
        return r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def _exact(artist: str, title: str, album: str, field: str) -> str | None:
    if not (artist or title):
        return None
    params = {"track_name": title}
    if artist:
        params["artist_name"] = artist
    if album:
        params["album_name"] = album
    return (_get("get", params) or {}).get(field) or None


def _search(artist: str, title: str, field: str) -> str | None:
    if not (artist and title):
        return None
    for item in _get("search", {"q": f"{artist} {title}"}) or []:
        if (item.get(field)
                and _same(_clean_artist(artist), _clean_artist(item.get("artistName", "")))
                and _same(_clean_title(title), _clean_title(item.get("trackName", "")))):
            return item[field]
    return None


def _lookup(artist: str, title: str, album: str, field: str) -> str | None:
    ca, ct = _clean_artist(artist), _clean_title(title)
    return (_exact(artist, title, album, field)
            or _exact(ca, ct, "", field)
            or _search(ca, ct, field))


# ------------------------------------------------------------------ #
#  Public API                                                         #
# ------------------------------------------------------------------ #

def fetch_synced_lyrics(artist: str, title: str, album: str = "") -> list[tuple[float, str]] | None:
    """Timestamped lyrics, or None if LRClib has none. Misses are cached too."""
    cached = _load_cache(artist, title)
    if cached is not None:
        return [tuple(item) for item in cached] or None

    lrc = _lookup(artist, title, album, "syncedLyrics")
    lyrics = parse_lrc(lrc) if lrc else None
    _save_cache(artist, title, lyrics or [])
    return lyrics


def fetch_plain_lyrics(artist: str, title: str, album: str = "") -> str | None:
    """Untimed lyrics text, used when no synced version exists."""
    return _lookup(artist, title, album, "plainLyrics")
