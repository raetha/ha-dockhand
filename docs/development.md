# Development Guide

## Running the test suite

The test suite uses [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component) (PHCC), which provides the same testing infrastructure as Home Assistant core. It requires **Python 3.14.2+** and pins to a specific HA release.

### Using the test script

A unified `scripts/run_tests.sh` handles both the sandbox-safe subset and the full PHCC suite:

```bash
# Sandbox-safe: ruff + AST check + HA-independent tests (Python 3.12+ ok)
bash scripts/run_tests.sh

# Full suite: everything above + all pytest tests via PHCC (requires Python 3.14.2+)
bash scripts/run_tests.sh --full

# Full suite in a specific venv
bash scripts/run_tests.sh --full --venv .venv

# Additional pytest flags pass through
bash scripts/run_tests.sh --full -v         # verbose
bash scripts/run_tests.sh --full -x         # stop on first failure
bash scripts/run_tests.sh --full -k "coord" # filter by name
```

The script always runs steps 1–3 (ruff check, ruff format, AST syntax) regardless of mode. Step 4 is either the full pytest suite (`--full`) or just `test_api.py` + `test_workflows.py` (default).

When Python 3.14.2+ becomes available in the Claude sandbox, the single comment block in step 4 of the script can be uncommented to enable the full suite there too.

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

# Run only the HA-independent tests (works on Python 3.12+)
pytest tests/test_api.py tests/test_workflows.py
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

The Claude development sandbox runs Python 3.12 and cannot install PHCC or HA 2026.x. After code changes, Claude runs:
- **ruff check + format** — full lint and format validation (always possible)
- **AST syntax check** — catches syntax errors without imports
- **261 of 354 tests** — all tests that don't require a real `hass` fixture:
  - `test_api.py` (28) — fully sandbox-safe
  - `test_workflows.py` (6) — fully sandbox-safe
  - `test_entities.py` (137) — all entity unit tests use `MagicMock` coordinators
  - `test_update.py` (36) — all update entity tests use `MagicMock`
  - `test_coordinator.py` (5) — `_safe_list` and `_unwrap` helper tests only
  - `test_helpers.py` (49) — URL builders, DeviceInfo factories, pure logic; excludes the 17 `_ensure_*_devices` tests that need a real device registry

The 93 `hass`-dependent tests (`test_config_flow.py`, `test_init.py`, `_ensure_*_devices` in `test_helpers.py`, coordinator integration tests) require Python 3.14.2+ with PHCC. Push to GitHub and check CI for authoritative results on those.

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
├── test_api.py          # DockhandClient HTTP paths (Python 3.12+ compatible)
├── test_config_flow.py  # All config flow steps, options flow
├── test_coordinator.py  # Fast/slow coordinators, data shapes, error paths
├── test_entities.py     # All entity classes — native_value, metadata, actions
├── test_helpers.py      # URL builders, DeviceInfo factories, _ensure_*_devices
├── test_init.py         # Setup/unload, _register_devices, _cleanup_stale_registry
├── test_update.py       # ContainerUpdateEntity — install, release notes, available
└── test_workflows.py    # Static CI workflow validation (Python 3.12+ compatible)
```

```
custom_components/dockhand/
├── __init__.py          # Setup/unload, device registration, stale cleanup
├── api.py               # DockhandClient — Bearer token auth
├── binary_sensor.py     # Environment config/state binary sensors
├── button.py            # Container/stack restart buttons
├── config_flow.py       # URL probe → optional token step + options flow
├── const.py             # Constants and defaults
├── coordinator.py       # Fast (60s) + Slow (600s) + Update coordinators
├── diagnostics.py       # HA diagnostics support
├── helpers.py           # URL builders, DeviceInfo factories, device registration
├── sensor.py            # All sensor entities (env, container, stack, etc.)
├── strings.json         # Translation keys (must match translations/en.json)
├── switch.py            # Container/stack running switches
├── update.py            # Container image update entities
└── translations/        # One file per language, en.json = strings.json
```
