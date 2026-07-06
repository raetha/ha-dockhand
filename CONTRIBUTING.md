# Contributing

Contributions are welcome via pull requests at [github.com/raetha/ha-dockhand](https://github.com/raetha/ha-dockhand).

## Compatibility baseline

The table below records the last version of each upstream project that was
reviewed for API changes, breaking changes, and new features relevant to this
integration. Before starting new development work, check for releases newer
than the versions listed here.

| Project | Last reviewed | Where to check |
|---|---|---|
| Home Assistant Core | 2026.3 (minimum); tested against 2026.6.4; dev blog reviewed through 2026-07-05 | https://github.com/home-assistant/core/releases |
| Dockhand | v1.0.36 | https://github.com/Finsys/dockhand/releases |

Update this table (and the corresponding project memory entry) after each
review session.

## Development setup

1. Clone the repository
2. Install test dependencies in a Python 3.14.2+ venv:
   ```bash
   python3.14 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements_test.txt
   ```
3. Run the full suite (lint + tests): `bash scripts/run_tests.sh --full --venv .venv`
4. Or if the venv is already active: `bash scripts/run_tests.sh --full`

See [docs/development.md](docs/development.md) for full setup details, Docker alternative, and sandbox-mode usage.

## Before submitting a PR

- All tests pass (`bash scripts/run_tests.sh --full`)
- Ruff reports no lint issues (`ruff check custom_components/dockhand/`)
- Ruff formatting is clean (`ruff format --check custom_components/dockhand/`)
- If adding a new feature, update `CHANGELOG.md` under the current unreleased section

## Translations

The integration ships with machine-generated translations for the following languages:

| Code | Language |
|---|---|
| `de` | German |
| `es` | Spanish |
| `fr` | French |
| `it` | Italian |
| `nb` | Norwegian Bokmål |
| `nl` | Dutch |
| `pl` | Polish |
| `pt` | Portuguese |
| `sv` | Swedish |
| `zh-Hans` | Chinese (Simplified) |

These were generated as a starting point to make the integration more accessible to non-English speakers. Native speaker corrections and improvements are very welcome.

### Correcting an existing translation

1. Find the relevant file in `custom_components/dockhand/translations/` (e.g. `de.json` for German)
2. Edit the strings — every key in the file should have a corresponding entry in `en.json` as a reference
3. Submit a PR with a brief description of what was corrected and why

No Python knowledge or test suite familiarity is needed for translation-only PRs.

### Adding a new language

1. Copy `custom_components/dockhand/translations/en.json` to a new file named with the appropriate [BCP 47 language tag](https://www.iana.org/assignments/language-subtag-registry/language-subtag-registry) (e.g. `ko.json` for Korean, `cs.json` for Czech)
2. Translate all string values — do not translate JSON keys
3. Submit a PR — please mention in the description that you are a native or fluent speaker of the language

A few formatting rules to keep in mind:
- Do not translate technical terms that appear in the Dockhand UI itself (e.g. `dh_`, `API token`, `Stack`, `Image`, `Volume`)
- Preserve any `**bold**` markdown in description strings
- Do not add or remove any keys relative to `en.json`

## Testing approach

The test suite uses [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component) (PHCC), which provides the same testing infrastructure as Home Assistant core. Tests run against real HA internals pinned to a specific release (see `requirements_test.txt`).

All test files import from `custom_components.dockhand`, which loads `homeassistant` at module level. As a result, **all tests require Python 3.14.2+ with PHCC installed** — there is no HA-free subset.

All other test files require Python 3.14.2+ and PHCC. The CI workflow runs the full suite on every push. Coverage spans all API methods, all config flow steps and options flow, all three coordinators, all entity classes and platforms, all device registration helpers, all URL builders, update entity install/release_notes logic, and setup/unload lifecycle.
