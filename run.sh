#!/bin/bash
# run.sh — Launch the Apple Music Lyrics menu bar app

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# rumps needs a framework-linked Python (system Python, not Homebrew).
# Prefer in order: Xcode CLT python → /usr/bin/python3 → homebrew
PYTHON=""
for PY in \
    /Library/Developer/CommandLineTools/usr/bin/python3 \
    /usr/bin/python3 \
    /opt/homebrew/bin/python3; do
    if [ -x "$PY" ]; then
        PYTHON="$PY"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "❌ No python3 found. Install Xcode Command Line Tools: xcode-select --install"
    exit 1
fi

echo "🐍 Using Python: $PYTHON"

# Ensure dependencies are installed for this Python
"$PYTHON" -c "import rumps, requests, Quartz" 2>/dev/null || {
    echo "📦 Installing dependencies…"
    "$PYTHON" -m pip install -q rumps requests pyobjc-framework-Quartz
}

echo "🎵 Starting Apple Music Lyrics…"
"$PYTHON" app.py
