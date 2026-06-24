# Development Guide

## Running the test suite

The test suite uses [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component) (PHCC), which provides the same testing infrastructure as Home Assistant core. It requires **Python 3.14.2+** and pins to a specific HA release.

### Using the test script

A unified `scripts/run_tests.sh` handles both lint-only and the full PHCC suite, with each mode using an isolated venv created automatically on first run:

```bash
# Lint + AST only (any Python 3.x — no homeassistant required)
bash scripts/run_tests.sh

# Full suite: ruff + AST + all 373 pytest tests via PHCC (requires Python 3.14.2+)
bash scripts/run_tests.sh --full

# Full suite in a specific venv path
bash scripts/run_tests.sh --full --venv .my-venv

# Additional pytest flags pass through
bash scripts/run_tests.sh --full -v         # verbose
bash scripts/run_tests.sh --full -x         # stop on first failure
bash scripts/run_tests.sh --full -k "coord" # filter by name
```

Default mode (no flags) runs ruff check, ruff format, and AST syntax check in a lightweight `.venv-sandbox` venv. It does **not** run pytest because every test file imports from `custom_components.dockhand`, which imports `homeassistant` at module level — pytest cannot collect any tests without a real homeassistant install.

`--full` uses `.venv-full` (created with Python 3.14.2+, PHCC installed from `requirements_test.txt`) and runs all 373 tests.

### Manual pytest (if PHCC is installed)

```bash
# One-time venv setup
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt

# Run everything
pytest tests/

# Run a specific file
pytest tests/test_coordinator.py -v

# Run a specific test
pytest tests/test_api.py -v
```

### PHCC version ↔ HA version

PHCC patch versions increment daily with each HA release. The pin in `requirements_test.txt` should match the minimum supported HA version for this integration (currently 2026.3+).

| PHCC version | HA version  |
|--------------|-------------|
| 0.13.333     | 2026.5.4    |
| 0.13.317+    | Requires Python 3.14.2+ |

To update the pin after a new HA release: find the PHCC version corresponding to the new HA release on the [PHCC releases page](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component/releases) and update `requirements_test.txt`.

### Using Docker (no Python 3.14 required on host)

If your host doesn't have Python 3.14.2+, run tests in a container:

```bash
docker run --rm \
  -v "$(pwd)":/workspace \
  -w /workspace \
  python:3.14-slim \
  bash -c "pip install -r requirements_test.txt -q && pytest tests/"
```

### What CI validates

GitHub Actions (`.github/workflows/ci.yml`) runs the full suite on Python 3.14 with the pinned PHCC version. Push to a branch and check the CI result for authoritative test output.

### Sandbox limitations

The Claude development sandbox runs Python 3.12 and cannot install PHCC or HA 2026.x. Because every test file imports from `custom_components.dockhand` (which imports `homeassistant` at module level), pytest cannot collect any tests without a real homeassistant install.

After code changes, Claude runs:
- **ruff check + format** — full lint and format validation
- **AST syntax check** — catches syntax errors without imports

The full 373-test pytest suite requires Python 3.14.2+ with PHCC. Use your local dev environment or push to GitHub and check CI for authoritative test results.

## Code quality checks

```bash
# Lint
ruff check custom_components/

# Format check (does not modify files)
ruff format --check custom_components/

# Fix formatting in-place
ruff format custom_components/
```

Ruff config is in `.ruff.toml` at the repo root. CI runs both `ruff check` and `ruff format --check` on `custom_components/` only; tests are excluded from format checking.

## Project structure

```
tests/
├── conftest.py          # Shared fixtures, mock data, MockConfigEntry helpers
├── test_api.py          # DockhandClient HTTP paths
├── test_config_flow.py  # All config flow steps, options flow
├── test_coordinator.py  # Fast/slow coordinators, data shapes, error paths
├── test_entities.py     # All entity classes — native_value, metadata, actions
├── test_helpers.py      # URL builders, DeviceInfo factories, _ensure_*_devices
├── test_init.py         # Setup/unload, _register_devices, _cleanup_stale_registry
├── test_update.py       # ContainerUpdateEntity — install, release notes, available
└── test_workflows.py    # Static CI workflow validation
```

```
custom_components/dockhand/
├── __init__.py          # Setup/unload, device registration, stale cleanup
├── api.py               # DockhandClient — Bearer token auth
├── binary_sensor.py     # Environment config/state binary sensors
├── button.py            # Container/stack restart buttons
├── config_flow.py       # Setup (URL+SSL → optional token); Options (poll/features); Reconfigure (URL+SSL+token)
├── const.py             # Constants and defaults
├── coordinator.py       # Fast (60s) + Slow (600s) + Update coordinators
├── diagnostics.py       # HA diagnostics support
├── helpers.py           # URL builders, DeviceInfo factories, device registration
├── migration.py         # One-time registry migrations (async_run_migrations entry point)
├── sensor.py            # All sensor entities (env, container, stack, etc.)
├── strings.json         # Translation keys (must match translations/en.json)
├── switch.py            # Container/stack running switches
├── update.py            # Container image update entities
└── translations/        # One file per language, en.json = strings.json
```
