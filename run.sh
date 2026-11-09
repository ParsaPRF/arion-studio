#!/usr/bin/env bash
# Arion Studio launcher — Linux / macOS.
# Runs the app with the project's venv; runs install.sh first if needed.
cd "$(dirname "$0")"

if [ ! -x venv/bin/python ]; then
    echo "🎛  First run — installing…"
    bash install.sh
fi

exec ./venv/bin/python main.py "$@"
