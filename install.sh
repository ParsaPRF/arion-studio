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
if [ -d venv ] && [ ! -x venv/bin/python ]; then
    echo "⚠️  Existing venv is incomplete — rebuilding it..."
    rm -rf venv
fi
if [ ! -d venv ]; then
    "$PY" -m venv venv
fi
venv/bin/python -m pip --version >/dev/null 2>&1 || venv/bin/python -m ensurepip --upgrade
venv/bin/python -m pip install --upgrade pip --disable-pip-version-check --quiet

# pip needs a writable HTTP cache and $TMPDIR. A locked cache (read-only $HOME,
# full disk, snap/Flatpak confinement) makes pip wait with no output at all, so
# install cache-free and with bounded timeouts: a dead network then fails fast
# and the mirror fallback below can actually run.
PIP_FLAGS=(--no-cache-dir --disable-pip-version-check --no-input
           --prefer-binary --timeout 20 --retries 2)

echo "Installing python dependencies..."
echo "   About 5 MB to download; on a slow connection this can take a few minutes."

if ! venv/bin/python -m pip install "${PIP_FLAGS[@]}" -r requirements.txt; then
    echo "↻ PyPI unreachable — trying the runflare mirror..."
    venv/bin/python -m pip install "${PIP_FLAGS[@]}" \
        -i https://mirror-pypi.runflare.com/simple -r requirements.txt
fi

# Trust the imports, not just pip's exit code.
if ! venv/bin/python -c "import customtkinter, dotenv, requests, yt_dlp" >/dev/null 2>&1; then
    echo "❌ Dependencies installed but cannot be imported. Please report the output above."
    exit 1
fi
echo "✅ Dependencies ok"

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
