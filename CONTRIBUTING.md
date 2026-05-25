# Contributing

Contributions are welcome via pull requests at [github.com/raetha/ha-dockhand](https://github.com/raetha/ha-dockhand).

## Compatibility baseline

The table below records the last version of each upstream project that was
reviewed for API changes, breaking changes, and new features relevant to this
integration. Before starting new development work, check for releases newer
than the versions listed here.

| Project | Last reviewed | Where to check |
|---|---|---|
| Home Assistant Core | 2026.3 | https://github.com/home-assistant/core/releases |
| Dockhand | v1.0.29 | https://github.com/Finsys/dockhand/releases |

Update this table (and the corresponding project memory entry) after each
review session.

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

The test suite uses Python's stdlib `unittest` with a lightweight `ha_stubs` module
that provides accurate minimal stubs for all HA classes used by the integration.
No Home Assistant installation or external test framework is required — tests run
in plain Python with no network access needed.
