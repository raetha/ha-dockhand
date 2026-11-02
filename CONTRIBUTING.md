# Contributing

Contributions are welcome via pull requests at [github.com/raetha/ha-dockhand](https://github.com/raetha/ha-dockhand).

**Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before adding any new
entity, device, or config option.** It covers unique ID conventions, the
central entity-cleanup system, coordinator architecture, and the config
migration pattern — getting any of these wrong doesn't fail loudly, so
this is a required step, not optional background reading.

Before proposing a new feature, check [docs/BACKLOG.md](docs/BACKLOG.md)
— it records ideas that were already evaluated and deliberately deferred
or rejected, along with why, so they don't need re-litigating from
scratch.

## Compatibility baseline

The table below records the last version of each upstream project that was
reviewed for API changes, breaking changes, and new features relevant to this
integration. Before starting new development work, check for releases newer
than the versions listed here.

| Project | Last reviewed | Where to check |
|---|---|---|
| Home Assistant Core | 2026.3 (minimum); tested against 2026.10.4 (PHCC 0.13.375); 2026.8–2026.10 developer blog and core platform/coordinator source reviewed directly (2026-10-14) — only change needed was the deprecated `async_get_device(identifiers=...)` lookup, now feature-detected (`helpers._device_by_identifier`). Also ready for 2026.11's in-place entity_id renames (`async_entity_id_changed`; guarded by `tests/test_entity_lifecycle.py`) | https://github.com/home-assistant/core/releases |
| Dockhand | v1.0.54 (diffed v1.0.48→v1.0.54 source directly against every endpoint this integration calls, 2026-10-14 and 2026-10-19; `docs/DOCKHAND_API.md` regenerated at v1.0.54 — Dockhand now ships `@openapi` doc comments on most routes. Relevant: batch-update-stream can now skip a container inside a finished job (handled — Install reports it), the minimum-image-age cooldown keeps held updates out of `hasImageUpdate` (shown via `update_held_hours`), `/api/auto-update` now requires `schedules:view` (already needed for `/api/schedules`), new `env_report` schedule type; 1.0.54: `check-updates` reports a moved digest behind a digest-pinned image as `hasUpdate` plus `pinnedToDigest`; the client clears `hasUpdate` since Install can't apply it, and the update entity shows it as advisory. The dashboard stats' new `pinnedDigest`/`newerVersion` counts aren't used: the Containers sensor's own counts cover both and also see the precise check) | https://github.com/Finsys/dockhand/releases |

Update this table after each review session. When picking up new Dockhand
API work, also regenerate [docs/DOCKHAND_API.md](docs/DOCKHAND_API.md) —
a navigable index of Dockhand's REST routes — by running
`scripts/generate_dockhand_api_docs.py` against a fresh Dockhand clone.
Dockhand has no official OpenAPI spec ([Finsys/dockhand#814](https://github.com/Finsys/dockhand/issues/814),
open, unimplemented), so this generated index — built from whatever
leading doc comments exist on each route file — is the closest thing
available. It's a starting point (only a fraction of routes have doc
comments), not a substitute for reading the actual route source for
exact request/response shapes, especially for anything security- or
data-loss-sensitive.

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
- Ruff reports no lint issues on both `custom_components/dockhand/` and `tests/` (`ruff check custom_components/ tests/`)
- Ruff formatting is clean on both (`ruff format --check custom_components/ tests/`)
- If adding a new feature, update `CHANGELOG.md` under the current unreleased section (see "CHANGELOG discipline" below)
- If adding any new entity, device, or config option, work through [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)'s checklist (§5) — unique ID conventions, entity cleanup, and config migrations are easy to get subtly wrong with no visible symptom
- Never bump the version in `manifest.json`, and never mark a `CHANGELOG.md` section as released (dated, out of `[Unreleased]`), as part of a PR — that's a separate, deliberate release step the maintainer does after confirming everything in the PR actually works, not something to bundle in

## CHANGELOG discipline

`CHANGELOG.md`'s `[Unreleased]` section is release notes for end users, not
a development log. A few rules that keep it that way:

- **Never edit an already-released section** (anything with a version
  number and date above `[Unreleased]`). Those entries describe how that
  version worked at the time; a later change gets its own new entry in
  `[Unreleased]`, not a retroactive edit to history.
- **Describe the net difference for a user, not the journey.** If a bug
  was introduced and fixed within the same unreleased cycle — code that
  was only ever in development builds, never a release — don't add a
  "Fixed" entry narrating it. Just write the final `Added`/`Changed` entry
  as if the feature always worked that way; there's nothing to disclose
  about something that never shipped broken. Legitimate `Fixed` entries
  are only for bugs in already-released behavior. The same applies to a
  sub-aspect of an entirely new feature: if an entity is new this cycle,
  a detail of how it behaves (e.g. it dynamically relabels itself) is
  part of describing the new entity, not a separate `Changed` entry
  saying it "now" does something — there's no prior released state to
  contrast against.
- **Cut implementation detail.** API endpoints touched, which coordinator,
  internal architecture, migration mechanics — all useful in a commit
  message or code comment, not here. Focus on what a user actually
  notices: a new entity, a renamed setting, a behavior change.
- **Before a release, re-read the whole `[Unreleased]` section top to
  bottom** and cut anything that reads like an engineering journal rather
  than release notes.
- **Watch for a specific editing hazard**: a generic search anchor like
  `### Fixed` can match a heading that recurs in multiple version
  sections. Re-check where an edit actually landed, especially after
  inserting near a section boundary.

## Code style

Comments should explain **why**, not what or how — a non-obvious
constraint, a tradeoff, a reason something isn't the "obvious" approach.
They shouldn't restate what the code already says, narrate how a bug was
found, or preserve historical context about a previous version's
behavior (that belongs in `CHANGELOG.md` git history, not a comment that
will outlive its relevance). Before adding a comment, ask: would someone
competent in Python/Home Assistant need this to understand the code, or
is it documenting the journey to get here?

**Don't duplicate logic across platform files — extract it to `helpers.py`
instead, even for something small.** Six platform files
(`sensor.py`/`binary_sensor.py`/`button.py`/`number.py`/`select.py`/
`switch.py`/`update.py`) each having their own small per-container/
per-stack lookup, their own copy of an entity-registry "have I already
created this" check, etc. is exactly how a real bug shipped in 1.9.0: one
copy of the same idea quietly drifted from the others (different variable
name, then different implementation entirely), so a fix applied to the
"obvious" copies missed it. `helpers.py` already has real precedent for
this — `_coordinator_env()` itself replaced two near-identical
`_fast_env`/`_slow_env` functions for the same reason (see its own
docstring), and `already_registered()`/`_find_container()`/`_find_stack()`
are the same move applied again. This isn't about naming consistency for
its own sake — a full pass to make every variable name uniform across the
codebase would be high-risk churn for low value, and isn't the actual
fix. It's specifically about *logic* that exists in more than one place:
if you're about to write a loop/lookup/check that another platform file
already has a version of, that's the signal to add a shared helper
instead of a fourth (or eighth) copy, not a naming convention to follow
more carefully.

## Building a local test package

To produce a zip for manual testing (e.g. installing on a real Home
Assistant instance without HACS):

```bash
cd ha-dockhand && find . -not -path "./.git/*" -not -path "./.git" \
  -not -path "./.ruff_cache/*" -not -path "./.ruff_cache" \
  -not -path "./.pytest_cache/*" -not -path "./.pytest_cache" \
  -not -path "./.venv*/*" -not -path "./.venv*" \
  -not -path "*/__pycache__/*" -not -name "__pycache__" \
  -not -name "*.pyc" -not -name "*.bak" \
  | zip /path/to/ha-dockhand-VERSION.zip -@
```

## Versioning

This repo follows semver — see `docs/SEMVER.md` for what counts as major/minor/patch for this
repo specifically (it's also the canonical policy `ha-dockhand-cards` references, since the two
repos share a release flow). Decide the bump before working through the release checklist below.

## Release checklist

A more thorough pass than the PR checklist above, run before tagging a
release (not needed for every PR):

- `bash scripts/run_tests.sh --full`: ruff check/format on both `custom_components/` and `tests/`, mypy (strict), the quality scale rule check, and the full test suite with its 100% coverage gate — this now includes `test_config_flow.py`'s whole-tree translation coverage tests (see the "Translations" section below), so a missing/empty key or a locale that's drifted out of sync will already show up as a test failure here, not just at this checklist step
- `manifest.json`: version bumped, field order correct (`domain`, `name`, then alphabetical). `scripts/bump_version.sh X.Y.Z [YYYY-MM-DD]` does the bump: it sets the manifest version, turns `[Unreleased]` into the dated release section and updates the compare links, in one all-or-nothing step (pass the date when preparing a release ahead of the day it ships)
- `strings.json` and `translations/en.json` are byte-for-byte identical
- Every locale in `translations/` has exactly the same keys as `en.json` (no missing, no extra) — except `api_url`, which stays English everywhere
- Every entity `translation_key` used in code has both a `strings.json` and an `icons.json` entry, and vice versa (no orphans)
- `CHANGELOG.md`: compare-link references at the bottom are correct; re-read the `[Unreleased]` section per the CHANGELOG discipline above
- Quality scale review, per `docs/QUALITY_SCALE.md` "Release review": `run_tests.sh --full` already checks the rule list against Home Assistant's current one, strict typing and 100% line coverage; the review covers what those can't — rule requirements that changed, rules this release's additions touch, and `quality_scale.yaml` comments the release made stale. Add a line to that page's review log
- `README.md` matches the current entity list and behavior
- Config flow `CREATE_ENTRY` tests are preceded by whatever `setup_options`/options step they depend on
- The packaging command above produces a clean zip (nothing unexpected included)

## Translations

If your PR adds any new user-facing string (a new entity name, a config
option, an error message), add a machine-translated entry for that key
to all locale files in the same PR — don't leave it for a follow-up.
`strings.json` and `translations/en.json` must stay byte-for-byte
identical, and every other locale file must have exactly the same set of
keys (no missing, no extra) with the sole exception of `api_url`, which
stays in English everywhere.

**This is enforced by `test_config_flow.py`'s whole-tree translation
tests** (`test_strings_json_has_no_empty_leaf_values`,
`test_translations_en_json_matches_strings_json_exactly`,
`test_every_locale_covers_every_strings_json_key_with_non_empty_value`),
not just this checklist — they walk every single leaf value anywhere in
`strings.json`, so a new key added anywhere is covered automatically
with no test changes required. A real bug slipped past this exact
checklist item and was only caught by installing and looking at the
actual first-time-setup screen: `config.step.setup_options` (which
reuses the same options schema as the later Configure screen) had been
stale since before the 1.8.0 rename — missing `enable_runtime_controls`/
`enable_container_stats` entirely and still showing the pre-rename
`enable_updates` key — undetected for that whole time because nothing
checked it against the schema. `test_options_schema_fields_have_non_empty_translations`
and `test_options_schema_fields_have_data_description` close that
specific gap by walking the actual voluptuous schema and cross-checking
both `config.step.setup_options` and `options.step.init` against it,
since they're both driven by the same `_options_schema()` function and
need their own full copy of the translations.

**What none of these tests can do is confirm the *rendered shape* in
HA's frontend** — a key existing with a non-empty value doesn't
guarantee HA resolves it to the right place on screen. This bit twice in
the same 1.8.1 cycle: an attempt to visually group
`enable_update_entities`/`enable_precise_updates`/`poll_interval_updates`
(now `poll_interval_precise_updates`) via HA's `section()` helper kept showing those fields' labels as raw
config keys with no help text in a live instance, under two different
translation-JSON structures, and the actual cause was never confirmed —
these tests passed both times regardless, since the values existed and
were non-empty at the paths tried. Reverted rather than kept fighting
it; see docs/BACKLOG.md. Any future attempt at `section()` grouping (or
other structural form changes) needs an actual install-and-look pass
before merging — these tests are necessary but not sufficient for
anything involving how fields are visually laid out, only for whether
the underlying strings exist at all.

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

The CI workflow runs the full suite on every push. **Every line of the integration is covered, and CI fails if a change adds one no test runs** (`--cov-fail-under=100`). Add the test with the code. If a line truly can't be reached, that usually means it can be removed; `# pragma: no cover` is for the rare line that must stay but genuinely can't run under test, with a comment saying why. `tests/test_platform_setup.py` runs the real setup with every option on and one environment containing a bit of everything, which is the place to add data when a new entity's creation path needs covering.
