"""Run all tests. Execute from any directory: python3 tests/run_tests.py"""
import sys, os, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
sys.path.insert(0, ROOT)
sys.path.insert(0, TESTS)

from ha_stubs import install
install()

loader = unittest.TestLoader()
suite = loader.discover(start_dir=TESTS, pattern="test_*.py")
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
