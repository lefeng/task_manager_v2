#!/usr/bin/env bash
# Build taskman v2 as a frozen binary.
#
# Usage:
#   bash build.sh                  # Cython compile + cx_Freeze
#   bash build.sh --pyinstaller    # PyInstaller (single-dir dist/)
#   bash build.sh --compile-only   # Cython only, no packaging
#   bash build.sh --build-only     # cx_Freeze only (skip Cython)
#   bash build.sh --clean          # Remove compiled artifacts

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV_PYTHON="${SCRIPT_DIR}/.venv/bin/python"
if [ ! -f "$VENV_PYTHON" ]; then
    echo "No .venv found. Create it first:"
    echo "  python3.12 -m venv .venv && .venv/bin/pip install -e '.[build]'"
    exit 1
fi

if [[ "${1:-}" == "--pyinstaller" ]]; then
    echo "Building with PyInstaller..."
    "$VENV_PYTHON" -m PyInstaller spec/taskman.spec --distpath dist --workpath build/pyinstaller
    echo "Done. Output: dist/taskman/"
else
    "$VENV_PYTHON" setup_cython.py "${@}"
fi
