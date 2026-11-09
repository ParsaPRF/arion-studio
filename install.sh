#!/usr/bin/env bash
# Arion Studio installer — Linux / macOS.
# Installs system prerequisites (ffmpeg, tkinter if missing/possible),
# creates the Python venv, installs dependencies (with a regional PyPI
# mirror fallback for censored networks) and adds a menu entry + command.
#
# Usage:  ./install.sh

set -euo pipefail
cd "$(dirname "$0")"

echo "🎛  Installing Arion Studio…"

# --- 1) find a Python 3.10+ ---------------------------------------------------
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1; then
        if "$c" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >/dev/null 2>&1; then
            PY="$c"
            break
        fi
    fi
done
if [ -z "$PY" ]; then
    echo "❌ Python 3.10+ not found. Install it first:"
    echo "   Debian/Ubuntu: sudo apt install python3 python3-venv python3-pip"
    echo "   Fedora:        sudo dnf install python3"
    echo "   macOS:         brew install python"
    exit 1
fi
echo "✅ Python: $($PY --version)"

# --- 2) ffmpeg ----------------------------------------------------------------
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
    echo "⬇️  Installing ffmpeg…"
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update -y && sudo apt-get install -y ffmpeg
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y ffmpeg
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --noconfirm ffmpeg
    elif command -v brew >/dev/null 2>&1; then
        brew install ffmpeg
    else
        echo "⚠️  Could not install ffmpeg automatically — install it via your package manager."
    fi
else
    echo "✅ ffmpeg already present"
fi

# --- 3) tkinter (required by CustomTkinter) ------------------------------------
if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
    echo "Installing tkinter…"
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get install -y python3-tk
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3-tkinter
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --noconfirm tk
    else
        echo "⚠️  tkinter missing — install it for your Python ($PY) and re-run."
        exit 1
    fi
fi

# --- 4) venv + dependencies -----------------------------------------------------
if [ ! -d venv ]; then
    "$PY" -m venv venv
fi
venv/bin/pip install --upgrade pip --disable-pip-version-check --quiet
echo "Installing python dependencies…"
if ! venv/bin/pip install --disable-pip-version-check -r requirements.txt; then
    echo "↻ PyPI unreachable — trying the runflare mirror…"
    venv/bin/pip install --disable-pip-version-check \
        -i https://mirror-pypi.runflare.com/simple -r requirements.txt
fi

# --- 5) launcher + application menu entry ---------------------------------------
chmod +x run.sh
mkdir -p "$HOME/.local/bin"
ln -sf "$(cd "$(pwd)" && pwd)/run.sh" "$HOME/.local/bin/arion-studio"

if [ -n "${XDG_DATA_HOME:-}" ]; then APPS_DIR="$XDG_DATA_HOME/applications"; else APPS_DIR="$HOME/.local/share/applications"; fi
if [ -d "$APPS_DIR" ] || mkdir -p "$APPS_DIR" 2>/dev/null; then
    cat > "$APPS_DIR/arion-studio.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Arion Studio
Comment=Desktop subtitles, YouTube downloads and SRT translation
Exec=$HOME/.local/bin/arion-studio
Categories=AudioVideo;Utility;Network;
Terminal=false
EOF
fi

echo ""
echo "✅ Done. Launch with:"
echo "   arion-studio          (new terminal tab)"
echo "   ./run.sh              (from this folder)"
