#!/usr/bin/env bash
# run_tests.sh — create or reuse a venv, then run the Dockhand test suite.
#
# Usage (from anywhere in the repo):
#   bash scripts/run_tests.sh          # run all tests
#   bash scripts/run_tests.sh -v       # verbose output (one line per test)
#   bash scripts/run_tests.sh --failfast  # stop on first failure
#
# The venv lives at .venv/ in the repo root. It is created on first run and
# reused on subsequent runs. Python itself is the only requirement.

set -euo pipefail

# Resolve the repo root regardless of where the script is called from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV="${ROOT}/.venv"
PYTHON="${VENV}/bin/python3"

# ── Create or update the venv ───────────────────────────────────────────────
if [[ ! -f "${PYTHON}" ]]; then
    echo "Creating virtual environment at ${VENV} ..."
    python3 -m venv "${VENV}"
    echo "Virtual environment created."
else
    # Ensure the venv's Python still matches the system Python major.minor.
    # If Python was upgraded, recreate the venv.
    SYS_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    VENV_VER=$("${PYTHON}" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "none")
    if [[ "${SYS_VER}" != "${VENV_VER}" ]]; then
        echo "Python version changed (${VENV_VER} → ${SYS_VER}), recreating venv ..."
        rm -rf "${VENV}"
        python3 -m venv "${VENV}"
        echo "Virtual environment recreated."
    fi
fi

# ── The test suite uses only stdlib — no pip install step needed. ────────────
# If you add third-party test dependencies to requirements_test.txt in the
# future, uncomment the block below:
#
# REQ="${ROOT}/requirements_test.txt"
# if [[ -f "${REQ}" ]]; then
#     "${VENV}/bin/pip" install --quiet -r "${REQ}"
# fi

# ── Run tests ────────────────────────────────────────────────────────────────
echo ""
echo "Running Dockhand test suite ..."
echo "──────────────────────────────────────────────"
"${PYTHON}" "${ROOT}/tests/run_tests.py" "$@"
