#!/usr/bin/env bash
# PCBPro launcher for macOS and Linux: sets up a private Python environment on first run, then opens the app.
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Setting up PCBPro for the first time (close to 1 GB)..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python -m pcbpro "$@"
