#!/usr/bin/env bash
# run_tests.sh — run the Dockhand integration test suite
#
# Usage:
#   bash scripts/run_tests.sh                        # lint + AST only (no HA required)
#   bash scripts/run_tests.sh --full                 # full test suite (requires Python 3.14.2+)
#
# Both modes use an isolated venv created automatically on first run:
#   Default:  .venv-sandbox  (ruff + pytest stubs, no homeassistant)
#   --full:   .venv-full     (pytest-homeassistant-custom-component, which pins
#                             the HA release — see requirements_test.txt)
#
# Override the venv path:
#   bash scripts/run_tests.sh --full --venv .my-venv
#
# To force a clean rebuild of the venv, delete it before running:
#   rm -rf .venv-full && bash scripts/run_tests.sh --full
#
# Why pytest requires --full:
#   Every test file imports from custom_components.dockhand, which loads
#   __init__.py, which imports homeassistant at module level.  Without a real
#   homeassistant install (provided by PHCC) pytest cannot collect any tests.
#   PHCC requires Python 3.14.2+.
#
# See docs/development.md for venv setup instructions.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

FULL=0
VENV=""
PYTEST_EXTRA_ARGS=""

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

# ── Determine venv path and required Python ───────────────────────────────────
if [[ $FULL -eq 1 ]]; then
    VENV="${VENV:-.venv-full}"
    MODE_LABEL="full (PHCC, pinned HA per requirements_test.txt)"
else
    VENV="${VENV:-.venv-sandbox}"
    MODE_LABEL="lint + AST only (pytest requires --full)"
fi

# ── Create venv if it doesn't exist ──────────────────────────────────────────
if [[ ! -f "$VENV/bin/activate" ]]; then
    echo "[ setup ] Creating venv at $VENV ..."
    if [[ $FULL -eq 1 ]]; then
        python3.14 -m venv "$VENV" \
            || { echo "ERROR: python3.14 not found. Python 3.14.2+ is required for --full."; exit 1; }
        echo "[ setup ] Installing pytest-homeassistant-custom-component..."
        "$VENV/bin/pip" install -r requirements_test.txt -q
    else
        "${PYTHON:-python3}" -m venv "$VENV" \
            || { echo "ERROR: Could not create venv."; exit 1; }
        echo "[ setup ] Installing ruff..."
        "$VENV/bin/pip" install ruff -q
    fi
    echo "[ setup ] Done."
    echo ""
fi

# ── Activate venv ─────────────────────────────────────────────────────────────
# shellcheck disable=SC1091
source "$VENV/bin/activate"
PYTHON="$VENV/bin/python"

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')" 2>/dev/null || echo "unknown")
STEPS=$([[ $FULL -eq 1 ]] && echo 4 || echo 3)

echo "========================================"
echo " Dockhand test runner"
echo " Python: $PY_VERSION  ($PYTHON)"
echo " Mode:   $MODE_LABEL"
echo " Venv:   $VENV"
echo "========================================"
echo ""

FAILED=0

# ── Step 1: ruff lint ─────────────────────────────────────────────────────────
echo "[ 1/$STEPS ] ruff check custom_components/..."
ruff check custom_components/ && echo "        PASS" || { echo "        FAIL"; FAILED=1; }

# ── Step 2: ruff format check ─────────────────────────────────────────────────
echo "[ 2/$STEPS ] ruff format --check custom_components/..."
ruff format --check custom_components/ && echo "        PASS" || { echo "        FAIL"; FAILED=1; }

# ── Step 3: AST syntax check ──────────────────────────────────────────────────
echo "[ 3/$STEPS ] AST syntax check custom_components/..."
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

# ── Step 4: pytest (full mode only) ──────────────────────────────────────────
if [[ $FULL -eq 1 ]]; then
    echo "[ 4/$STEPS ] pytest tests/ (full suite)..."
    # shellcheck disable=SC2086
    "$PYTHON" -m pytest tests/ --tb=short $PYTEST_EXTRA_ARGS \
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
