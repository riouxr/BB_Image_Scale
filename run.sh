#!/usr/bin/env bash
# BB Image Scale — run from source. Creates a local venv on first launch.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$HERE/.venv"
STAMP="$VENV/.deps-stamp"

PY="${PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
    echo "[ERROR] python3 not found." >&2
    echo "        sudo dnf install python3" >&2
    exit 1
fi

if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
    echo "[ERROR] Python is missing Tk support." >&2
    echo "        sudo dnf install python3-tkinter" >&2
    exit 1
fi

if [[ ! -d "$VENV" ]]; then
    echo "[..] Creating virtual environment in .venv"
    "$PY" -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

if [[ ! -f "$STAMP" || "$HERE/requirements.txt" -nt "$STAMP" ]]; then
    echo "[..] Installing dependencies"
    python -m pip install --upgrade pip -q
    python -m pip install -q pillow tkinterdnd2
    touch "$STAMP"
fi

exec python "$HERE/bb_image_scale.py" "$@"
