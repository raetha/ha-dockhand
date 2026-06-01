#!/usr/bin/env bash
# run_tests.sh — run the Dockhand integration test suite
#
# Usage:
#   bash scripts/run_tests.sh                        # sandbox-safe subset (ruff + HA-independent tests)
#   bash scripts/run_tests.sh --full --venv .venv    # full suite; creates venv if missing
#   bash scripts/run_tests.sh --full                 # full suite using active venv / system Python
#
# First-time setup for --full:
#   python3.14 -m venv .venv
#   bash scripts/run_tests.sh --full --venv .venv
#
# Or if your venv is already activated:
#   source .venv/bin/activate
#   bash scripts/run_tests.sh --full
#
# In a properly set-up dev environment with PHCC installed, --full runs
# everything including coordinator, entity, init, and config flow tests
# against real HA internals.  Without --full, only the HA-independent tests
# (test_api.py, test_workflows.py) run — suitable for the Claude sandbox
# which runs Python 3.12 and cannot install HA 2026.x.
#
# See docs/development.md for venv setup instructions.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

FULL=0
VENV=""
PYTEST_EXTRA_ARGS=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --full)       FULL=1; shift ;;
        --venv)       VENV="$2"; shift 2 ;;
        -v|--verbose) PYTEST_EXTRA_ARGS="$PYTEST_EXTRA_ARGS -v"; shift ;;
        -x)           PYTEST_EXTRA_ARGS="$PYTEST_EXTRA_ARGS -x"; shift ;;
        -k)           PYTEST_EXTRA_ARGS="$PYTEST_EXTRA_ARGS -k $2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# Activate venv if specified
if [[ -n "$VENV" ]]; then
    if [[ ! -f "$VENV/bin/activate" ]]; then
        echo "Venv not found at $VENV — creating it..."
        python3.14 -m venv "$VENV" || { echo "ERROR: Failed to create venv. Is Python 3.14.2+ installed?"; exit 1; }
        source "$VENV/bin/activate"
        pip install -r requirements_test.txt -q
    else
        # shellcheck disable=SC1091
        source "$VENV/bin/activate"
    fi
fi

PYTHON="${PYTHON:-python3}"
PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>/dev/null || echo "unknown")

echo "========================================"
echo " Dockhand test runner"
echo " Python: $PY_VERSION  ($PYTHON)"
echo " Mode:   $([ $FULL -eq 1 ] && echo 'full (PHCC)' || echo 'sandbox (HA-independent only)')"
echo "========================================"
echo ""

FAILED=0

# ── Step 1: ruff lint ──────────────────────────────────────────────────────
echo "[ 1/4 ] ruff check custom_components/..."
if command -v ruff &>/dev/null; then
    ruff check custom_components/ && echo "        PASS" || { echo "        FAIL"; FAILED=1; }
else
    echo "        SKIP (ruff not installed — pip install ruff)"
fi

# ── Step 2: ruff format check ─────────────────────────────────────────────
echo "[ 2/4 ] ruff format --check custom_components/..."
if command -v ruff &>/dev/null; then
    ruff format --check custom_components/ && echo "        PASS" || { echo "        FAIL"; FAILED=1; }
else
    echo "        SKIP (ruff not installed)"
fi

# ── Step 3: AST syntax check (all source files) ───────────────────────────
echo "[ 3/4 ] AST syntax check custom_components/..."
"$PYTHON" - << 'PYEOF'
import ast, os, sys
errors = []
for root, dirs, files in os.walk("custom_components/dockhand"):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for f in files:
        if f.endswith(".py"):
            path = os.path.join(root, f)
            try:
                ast.parse(open(path).read(), filename=path)
            except SyntaxError as e:
                errors.append(f"  {path}:{e.lineno}: {e.msg}")
if errors:
    print("FAIL")
    for e in errors:
        print(e)
    sys.exit(1)
else:
    print("        PASS")
PYEOF
AST_EXIT=$?
[[ $AST_EXIT -ne 0 ]] && FAILED=1

# ── Step 4: pytest ────────────────────────────────────────────────────────
if [[ $FULL -eq 1 ]]; then
    echo "[ 4/4 ] pytest tests/ (full suite — requires PHCC + Python 3.14.2+)..."
    # Verify Python version
    PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")
    PY_MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
    PY_MICRO=$("$PYTHON" -c "import sys; print(sys.version_info.micro)")
    if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 14 ]]; } || \
       { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -eq 14 ]] && [[ "$PY_MICRO" -lt 2 ]]; }; then
        echo "        ERROR: --full requires Python 3.14.2+, got $PY_VERSION"
        echo "               Use --venv to point at a 3.14.2+ venv, or omit --full for sandbox mode."
        FAILED=1
    elif ! "$PYTHON" -c "import pytest" 2>/dev/null; then
        echo "        ERROR: pytest not found in the current Python environment ($PY_VERSION)"
        echo ""
        echo "        To fix, either:"
        echo "          1. Use --venv to auto-create and use a venv:"
        echo "               bash scripts/run_tests.sh --full --venv .venv"
        echo "          2. Activate an existing venv first:"
        echo "               source .venv/bin/activate && bash scripts/run_tests.sh --full"
        echo "          3. Install dependencies manually:"
        echo "               pip install -r requirements_test.txt"
        echo ""
        FAILED=1
    else
        # shellcheck disable=SC2086
        "$PYTHON" -m pytest tests/ --tb=short $PYTEST_EXTRA_ARGS && echo "        PASS" || { echo "        FAIL"; FAILED=1; }
    fi
else
    echo "[ 4/4 ] pytest (HA-independent subset — 261 of 354 tests)..."
    # Files with zero hass fixtures — run entirely:
    #   test_api.py (28), test_workflows.py (6), test_entities.py (137), test_update.py (36)
    # Files with mixed coverage — run only the pure tests:
    #   test_coordinator.py: 5 pure (safe_list/unwrap helpers), 19 hass-dependent excluded
    #   test_helpers.py: 49 pure (URL builders, DeviceInfo factories, pure logic),
    #                    17 hass-dependent (_ensure_*_devices) excluded
    # Fully hass-dependent — excluded entirely:
    #   test_config_flow.py (16), test_init.py (41)
    # Full suite (all 354 tests) requires Python 3.14.2+ with PHCC.
    # TODO: once Python 3.14.2+ is available in this environment, replace with:
    #   "$PYTHON" -m pytest tests/ --tb=short $PYTEST_EXTRA_ARGS
    # shellcheck disable=SC2086
    "$PYTHON" -m pytest \
        tests/test_api.py \
        tests/test_workflows.py \
        tests/test_entities.py \
        tests/test_update.py \
        tests/test_coordinator.py::test_safe_list_with_list \
        tests/test_coordinator.py::test_safe_list_with_none \
        tests/test_coordinator.py::test_safe_list_with_dict \
        tests/test_coordinator.py::test_unwrap_value \
        tests/test_coordinator.py::test_unwrap_exception \
        --tb=short $PYTEST_EXTRA_ARGS \
        && "$PYTHON" -m pytest \
        tests/test_helpers.py -k "not (ensure_env_devices or ensure_hub_devices)" \
        --tb=short $PYTEST_EXTRA_ARGS \
        && echo "        PASS" || { echo "        FAIL"; FAILED=1; }
fi

echo ""
echo "========================================"
if [[ $FAILED -eq 0 ]]; then
    echo " ALL CHECKS PASSED"
else
    echo " ONE OR MORE CHECKS FAILED"
fi
echo "========================================"

exit $FAILED
