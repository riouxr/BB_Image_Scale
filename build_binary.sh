#!/usr/bin/env bash
# BB Image Scale — build a single-file Linux executable into dist/
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

echo
echo " ================================================"
echo "  BB Image Scale  --  Build"
echo " ================================================"
echo

PY="${PYTHON:-python3}"

if ! command -v "$PY" >/dev/null 2>&1; then
    echo " [ERROR] python3 not found.  sudo dnf install python3" >&2
    exit 1
fi

if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
    echo " [ERROR] Tk missing.  sudo dnf install python3-tkinter" >&2
    exit 1
fi

echo " [OK] $("$PY" --version)"

VENV="$HERE/.venv"
[[ -d "$VENV" ]] || "$PY" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"

echo " [..] Installing build dependencies"
python -m pip install --upgrade pip -q
python -m pip install -q -r requirements.txt
echo " [OK] Dependencies ready"
echo

echo " [..] Building (takes 30-90 seconds)"
python -m PyInstaller \
    --onefile \
    --windowed \
    --clean \
    --noconfirm \
    --name "BBImageScale" \
    --hidden-import="PIL._tkinter_finder" \
    --collect-all tkinterdnd2 \
    bb_image_scale.py

echo
echo " ================================================"
echo "  BUILD COMPLETE"
echo " ================================================"
echo
echo "  Your app:  dist/BBImageScale"
echo "  Install it in the app menu with:  ./install.sh"
echo
