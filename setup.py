"""
setup.py — py2app build configuration for shipping as a .app / .dmg.

Build via ./build_dmg.sh (recommended) or:
    pip install py2app
    python3 setup.py py2app
"""
from __future__ import annotations

from setuptools import setup

APP_NAME      = "Suaraloe"
BUNDLE_ID     = "com.satusembilan.revealer"
APP_VERSION   = "1.0.0"
BUILD_NUMBER  = "1"
COPYRIGHT     = "Copyright © 2026 satusembilan. All rights reserved."


plist = {
    "CFBundleName":               APP_NAME,
    "CFBundleDisplayName":        APP_NAME,
    # CFBundleExecutable is set by py2app to match the binary it actually
    # writes to Contents/MacOS/ — don't override or LaunchServices will fail.
    "CFBundleIdentifier":         BUNDLE_ID,
    "CFBundleShortVersionString": APP_VERSION,
    "CFBundleVersion":            BUILD_NUMBER,
    "NSHumanReadableCopyright":   COPYRIGHT,
    # Menubar-only app: no Dock icon, no main window.
    "LSUIElement":                True,
    # Required to control Music.app via AppleScript (the permission prompt
    # users see on first launch shows this string).
    "NSAppleEventsUsageDescription":
        "Suaraloe reads the currently playing track from "
        "Music.app to display synced lyrics.",
    "LSMinimumSystemVersion":     "11.0",
}

OPTIONS = {
    "argv_emulation": False,
    "plist":          plist,
    "packages":       ["rumps", "requests", "Quartz"],
    "includes":       ["music_bridge", "lyrics_fetcher", "lyric_sync", "card"],
    "excludes":       ["tkinter"],
    "iconfile":       "icon.icns",
}

setup(
    app=["app.py"],
    name=APP_NAME,
    version=APP_VERSION,
    author="satusembilan",
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
