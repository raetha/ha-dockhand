"""Run all tests and lint. Execute from any directory: python3 tests/run_tests.py

Runs in two phases:
  1. Ruff lint check on custom_components/dockhand/ (skipped with a warning
     if ruff is not installed, so the test suite still works without it)
  2. Full unittest suite

Exit code is non-zero if either phase fails.
"""
import subprocess, sys, os, unittest, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
TARGET = os.path.join(ROOT, "custom_components", "dockhand")

sys.path.insert(0, ROOT)
sys.path.insert(0, TESTS)

from ha_stubs import install
install()

# ── Phase 1: ruff lint ────────────────────────────────────────────────────────

lint_ok = True
if shutil.which("ruff"):
    print("── Ruff lint ────────────────────────────────────────────────────────")
    r1 = subprocess.run(["ruff", "check", TARGET], capture_output=False)
    r2 = subprocess.run(["ruff", "format", "--check", TARGET], capture_output=False)
    lint_ok = r1.returncode == 0 and r2.returncode == 0
    if lint_ok:
        print("Lint: OK\n")
    else:
        print("\nLint: FAILED (run `ruff check` and/or `ruff format` to see details)\n")
else:
    print("── Ruff lint ────────────────────────────────────────────────────────")
    print("WARNING: ruff not found — skipping lint. Install with: pip install ruff\n")

# ── Phase 2: unittest suite ───────────────────────────────────────────────────

print("── Unit tests ───────────────────────────────────────────────────────")
loader = unittest.TestLoader()
suite = loader.discover(start_dir=TESTS, pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
tests_ok = result.wasSuccessful()

# ── Exit ──────────────────────────────────────────────────────────────────────

if not lint_ok or not tests_ok:
    sys.exit(1)
