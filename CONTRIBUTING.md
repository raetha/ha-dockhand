# Contributing

Contributions are welcome via pull requests at [github.com/raetha/ha-dockhand](https://github.com/raetha/ha-dockhand).

## Development setup

1. Clone the repository
2. Install test dependencies: `pip install ruff` (requires Python 3.14+)
3. Run the full suite (lint + tests): `python3 tests/run_tests.py`
4. Or use the venv script: `bash scripts/run_tests.sh`

## Before submitting a PR

- All tests pass (`python3 tests/run_tests.py`)
- Ruff reports no lint issues (`ruff check custom_components/dockhand/`)
- Ruff formatting is clean (`ruff format --check custom_components/dockhand/`)
- If adding a new feature, update `CHANGELOG.md` under the current unreleased section

## Testing approach

The test suite uses Python's stdlib `unittest` with a lightweight `ha_stubs` module
that provides accurate minimal stubs for all HA classes used by the integration.
No Home Assistant installation or external test framework is required — tests run
in plain Python with no network access needed.
