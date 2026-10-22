"""app.py — Apple Music synced lyrics in an always-on-top translucent card."""
from __future__ import annotations

import re
import threading
import time

import AppKit
import rumps

from card import LyricsCard
from lyric_sync import find_current_line
from lyrics_fetcher import fetch_plain_lyrics, fetch_synced_lyrics
from music_bridge import get_plain_lyrics, is_music_running, make_estimated_lyrics, poll_player

UI_INTERVAL = 0.05             # card refresh (20 Hz)
PLAYER_POLL_INTERVAL = 0.25    # AppleScript polling, decoupled from the UI
LYRIC_LOOKAHEAD = 0.15         # show each line slightly before its timestamp
ADAPT_INTERVAL = 0.4           # how often the card re-checks its backdrop colour
CONTEXT = 1                    # lines shown before / after the current one

TEXT_MODES = {
    "auto":  "Auto (follows background)",
    "dark":  "Always Dark",
    "light": "Always White",
}


def clean(text: str) -> str:
    """Collapse whitespace; the card wraps long lines instead of truncating."""
    return re.sub(r"\s+", " ", text).strip()


class LyricsApp(rumps.App):
    def __init__(self):
        super().__init__("🎵", quit_button=None)

        self._card: LyricsCard | None = None   # built lazily on the main thread
        self._card_enabled = True
        self._icon_ready = False
        self._last_adapt = 0.0

        # Track state, shared with the fetch thread under _lock.
        self._lock = threading.Lock()
        self._track_key: tuple[str, str] | None = None
        self._lyrics: list[tuple[float, str]] | None = None
        self._fetching = False

        # The poller thread caches player state; UI ticks read it and interpolate
        # the position locally so the card can refresh without waiting on AppleScript.
        self._player: dict | None = None
        self._player_time = time.monotonic()

        self._last_idx: int | None = None
        self._last_render: tuple | None = None

        saved = AppKit.NSUserDefaults.standardUserDefaults().stringForKey_("textMode")
        self._text_mode = saved if saved in TEXT_MODES else "auto"

        self._card_item = rumps.MenuItem("Show Lyrics Card", callback=self._toggle_card)
        self._card_item.state = 1
        self._song_item = rumps.MenuItem("Song: —")

        text_menu = rumps.MenuItem("Text Color")
        self._mode_items = {}
        for mode, title in TEXT_MODES.items():
            item = rumps.MenuItem(title, callback=self._pick_text_mode)
            item.state = int(mode == self._text_mode)
            self._mode_items[mode] = item
            text_menu.add(item)

        self.menu = [
            self._card_item,
            text_menu,
            rumps.separator,
            self._song_item,
            rumps.separator,
            rumps.MenuItem("Quit", callback=rumps.quit_application),
        ]

        threading.Thread(target=self._poll_loop, daemon=True).start()

    # ---------------------------------------------------------------- menu

    def _toggle_card(self, sender) -> None:
        self._card_enabled = not self._card_enabled
        sender.state = int(self._card_enabled)
        if not self._card_enabled and self._card is not None:
            self._card.hide()

    def _pick_text_mode(self, sender) -> None:
        self._text_mode = next(m for m, item in self._mode_items.items() if item is sender)
        for mode, item in self._mode_items.items():
            item.state = int(mode == self._text_mode)
        AppKit.NSUserDefaults.standardUserDefaults().setObject_forKey_(self._text_mode, "textMode")
        if self._card is not None:
            self._card.set_mode(self._text_mode)

    def _ensure_native_icon(self) -> None:
        """Swap the emoji title for a template SF Symbol once the status item exists."""
        if self._icon_ready:
            return
        try:
            status_item = self._nsapp.nsstatusitem
            if status_item is None:
                return
            img = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_("music.note", None)
            if img is not None:
                img.setTemplate_(True)
                img.setSize_((13, 13))
                status_item.setImage_(img)
                self.title = ""
            self._icon_ready = True
        except Exception:
            pass

    # ------------------------------------------------------------- polling

    def _poll_loop(self) -> None:
        while True:
            try:
                state = poll_player() if is_music_running() else None
            except Exception:
                state = None
            with self._lock:
                self._player = state
                self._player_time = time.monotonic()
            time.sleep(PLAYER_POLL_INTERVAL)

    def _fetch_lyrics(self, artist: str, title: str, album: str, duration: float) -> None:
        lyrics = fetch_synced_lyrics(artist, title, album)
        if lyrics is None:
            plain = fetch_plain_lyrics(artist, title, album) or get_plain_lyrics()
            if plain:
                lyrics = make_estimated_lyrics(plain, duration)

        with self._lock:
            if self._track_key == (artist, title):
                self._lyrics = lyrics
                self._fetching = False

    # ---------------------------------------------------------------- tick

    @rumps.timer(UI_INTERVAL)
    def update(self, _):
        self._ensure_native_icon()
        if self._card is None:
            self._card = LyricsCard()
            self._card.set_mode(self._text_mode)
        now = time.monotonic()
        if self._card.is_shown and now - self._last_adapt > ADAPT_INTERVAL:
            self._last_adapt = now
            self._card.adapt()

        with self._lock:
            state, cached_at = self._player, self._player_time
        if state is None:
            self._set_idle()
            return

        key = (state["artist"], state["title"])
        with self._lock:
            new_track = key != self._track_key
            if new_track:
                self._track_key = key
                self._lyrics = None
                self._fetching = True
            lyrics, fetching = self._lyrics, self._fetching

        if new_track:
            self._song_item.title = f"♪  {state['title']} — {state['artist']}"
            self._last_render = self._last_idx = None
            self._show_message("Fetching lyrics…")
            threading.Thread(
                target=self._fetch_lyrics,
                args=(state["artist"], state["title"], state["album"], state["duration"]),
                daemon=True,
            ).start()
            return

        if lyrics is None:
            self._show_message("Fetching lyrics…" if fetching else "No lyrics found")
            return

        elapsed = now - cached_at if state["playing"] else 0.0
        idx = find_current_line(lyrics, state["position"] + elapsed + LYRIC_LOOKAHEAD)

        render = (idx, state["playing"])
        if render == self._last_render:
            return
        self._last_render = render

        slots = []
        for off in range(-CONTEXT, CONTEXT + 1):
            i = idx + off
            if off == 0 and idx < 0:
                slots.append("…")
            elif 0 <= i < len(lyrics):
                slots.append(clean(lyrics[i][1]))
            else:
                slots.append("")
        if not state["playing"]:
            slots[CONTEXT] = "⏸ " + slots[CONTEXT]

        # Glide when the lyric steps forward by one; otherwise cross-fade or update in place.
        if self._last_idx is not None and idx == self._last_idx + 1 and state["playing"]:
            mode = "advance"
        elif idx == self._last_idx:
            mode = "none"
        else:
            mode = "fade"
        self._last_idx = idx
        self._show_card(slots, mode)

    # ---------------------------------------------------------------- card

    def _show_message(self, text: str) -> None:
        self._show_card(["", text, ""], "fade")

    def _show_card(self, slots: list[str], mode: str) -> None:
        if self._card is not None and self._card_enabled:
            self._card.set_lines(slots, mode)
            self._card.show()

    def _set_idle(self) -> None:
        with self._lock:
            self._track_key = None
            self._lyrics = None
            self._fetching = False
        if self._card is not None:
            self._card.hide()
        self._song_item.title = "Song: —"
        self._last_render = None


if __name__ == "__main__":
    LyricsApp().run()
