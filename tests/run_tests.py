"""Run all tests and lint. Execute from any directory: python3 tests/run_tests.py

Runs in two phases:
  1. Ruff lint check on custom_components/dockhand/ (skipped with a warning
     if ruff is not installed, so the test suite still works without it)
  2. Full unittest suite

Exit code is non-zero if either phase fails.
"""

import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
TARGET = os.path.join(ROOT, "custom_components", "dockhand")

sys.path.insert(0, ROOT)
sys.path.insert(0, TESTS)

from ha_stubs import install

install()

# ── Phase 1: ruff lint ────────────────────────────────────────────────────────
# In CI, lint runs as its own dedicated job (with ruff installed) so we skip
# it here to avoid a noisy warning when ruff is not present in the test step.
# Locally, lint runs if ruff is installed and is skipped with a hint if not.

lint_ok = True
in_ci = os.environ.get("CI") == "true"
if in_ci:
    print("── Ruff lint ────────────────────────────────────────────────────────")
    print("CI detected — lint handled by dedicated lint job, skipping here.\n")
elif shutil.which("ruff"):
    print("── Ruff lint ────────────────────────────────────────────────────────")
    r1 = subprocess.run(["ruff", "check", TARGET], capture_output=False)
    r2 = subprocess.run(["ruff", "format", "--check", TARGET], capture_output=False)
    # Note: ruff format is intentionally excluded from tests/ — the lazy-import
    # and bootstrap patterns in test files are incompatible with ruff format.
    lint_ok = r1.returncode == 0 and r2.returncode == 0
    if lint_ok:
        print("Lint: OK\n")
    else:
        print("\nLint: FAILED (run `ruff check` and/or `ruff format` to see details)\n")
else:
    print("── Ruff lint ────────────────────────────────────────────────────────")
    print("ruff not found — skipping lint. Install with: pip install ruff\n")

# ── Phase 2: unittest suite ───────────────────────────────────────────────────

print("── Unit tests ───────────────────────────────────────────────────────")
loader = unittest.TestLoader()
suite = loader.discover(start_dir=TESTS, pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
tests_ok = result.wasSuccessful()

# ── Exit ──────────────────────────────────────────────────────────────────────

if not lint_ok or not tests_ok:
    sys.exit(1)
