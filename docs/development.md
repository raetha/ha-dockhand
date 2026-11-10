# Developing Dockhand

The canonical guide for working on this repo. How the integration works and why is in
[architecture.md](architecture.md) — **read it before adding any entity, device or config
option**, and work through its §5 checklist; ideas already evaluated and set aside are in
[backlog.md](backlog.md); what counts as a major, minor or patch change is
[semver.md](semver.md) (also the policy ha-dockhand-cards follows); the quality scale process is
[quality-scale.md](quality-scale.md); reviews are recorded in [audits.md](audits.md).

## Layout

| Path | What it is |
| --- | --- |
| `custom_components/dockhand/` | The integration: platforms, coordinators, config flow, migrations, translations, `quality_scale.yaml` |
| `tests/` | The full test suite (PHCC), held to the same lint and format standard as the integration |
| `scripts/run_tests.sh` | Runs what CI runs: ruff, mypy, the quality scale rule check, pytest with 100% coverage |
| `scripts/release.py` | Changelog check, release notes, test-build versions and the `dockhand.zip` HACS installs, used by CI |
| `scripts/bump_version.sh` | Prepares a release pull request (version, dated changelog section, compare links) |
| `scripts/check_quality_scale.py` | Compares `quality_scale.yaml` with Home Assistant's current rule list |
| `docs/` | This guide, architecture, backlog, semver policy, quality scale, Dockhand API index, design notes, audits |
| `.github/workflows/build.yml` | All of CI: checks, releases, test builds (see "What CI does"); `stale.yml` marks inactive issues |

## Testing

The test suite uses [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component) (PHCC), which provides the same testing infrastructure as Home Assistant core. It requires **Python 3.14.2+** and pins to a specific HA release.

### Using the test script

A unified `scripts/run_tests.sh` handles both lint-only and the full PHCC suite, with each mode using an isolated venv created automatically on first run:

```bash
# Lint + AST only (any Python 3.x — no homeassistant required)
bash scripts/run_tests.sh

# Full: ruff + AST + mypy (strict) + quality scale rule check + all pytest
# tests via PHCC with a 100% line coverage gate (requires Python 3.14.2+; the rule
# check fetches Home Assistant's rule list from GitHub)
bash scripts/run_tests.sh --full

# Full suite in a specific venv path
bash scripts/run_tests.sh --full --venv .my-venv

# Additional pytest flags pass through
bash scripts/run_tests.sh --full -v         # verbose
bash scripts/run_tests.sh --full -x         # stop on first failure
bash scripts/run_tests.sh --full -k "coord" # filter by name
```

Default mode (no flags) runs ruff check, ruff format, and AST syntax check in a lightweight `.venv-sandbox` venv. It does **not** run pytest because every test file imports from `custom_components.dockhand`, which imports `homeassistant` at module level — pytest cannot collect any tests without a real homeassistant install.

`--full` uses `.venv-full` (created with Python 3.14.2+, PHCC installed from `requirements_test.txt`) and runs all pytest tests.

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

PHCC patch versions increment with each HA release. The pin in `requirements_test.txt` tracks the latest stable HA release (Dependabot proposes bumps), so the suite runs against what most users have installed; the minimum supported HA version (currently 2026.3) is declared separately in `hacs.json`.

| PHCC version | HA version  |
|--------------|-------------|
| 0.13.372     | 2026.10.1   |
| 0.13.317+    | Requires Python 3.14.2+ |

To update the pin after a new HA release: find the PHCC version corresponding to the new HA release on the [PHCC releases page](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component/releases) and update `requirements_test.txt`.

### Testing approach

The test suite uses [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component) (PHCC), which provides the same testing infrastructure as Home Assistant core. Tests run against real HA internals pinned to a specific release (see `requirements_test.txt`).

All test files import from `custom_components.dockhand`, which loads `homeassistant` at module level. As a result, **all tests require Python 3.14.2+ with PHCC installed** — there is no HA-free subset.

CI runs the full suite on every push and pull request. **Every line of the integration is covered, and CI fails if a change adds one no test runs** (`--cov-fail-under=100`). Add the test with the code. If a line truly can't be reached, that usually means it can be removed; `# pragma: no cover` is for the rare line that must stay but genuinely can't run under test, with a comment saying why. `tests/test_platform_setup.py` runs the real setup with every option on and one environment containing a bit of everything, which is the place to add data when a new entity's creation path needs covering.

### Claude sandbox

The Claude development sandbox does not have Python 3.14 preinstalled, and
building CPython from source takes too long to redo every session. Instead,
Claude uses [`uv`](https://github.com/astral-sh/uv) to fetch a prebuilt
CPython from the [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
project's GitHub release assets — this works within the sandbox's network
allowlist (`release-assets.githubusercontent.com`) and takes seconds instead
of tens of minutes:

```bash
pip install --upgrade uv --break-system-packages   # upgrade from sandbox's stale uv (≥0.12.x needed for 3.14.x)
uv python install 3.14        # fetches a prebuilt 3.14.x (e.g. 3.14.7), no compiling
uv venv --python 3.14 .venv
uv pip install -r requirements_test.txt --python .venv/bin/python
bash scripts/run_tests.sh --full --venv .venv
```

**Important:** The sandbox ships an outdated `uv` (e.g. v0.8.x) at
`/root/.local/bin/uv` that only resolves `3.14` to a release candidate.
The `pip install --upgrade uv` step installs a current uv at
`/usr/local/bin/uv` which takes precedence and fetches the final 3.14.x
release. Skip this step and you'll get rc2 instead of the real thing.

This gives Claude a real, working Python 3.14.x with PHCC installed, so the
full pytest suite (not just ruff + AST) can run in-sandbox routinely. Docker
is not viable in this sandbox: no `docker` binary is available, and the
egress proxy blocks all container registries (confirmed via a direct
`403 host_not_allowed` from Docker Hub), so it isn't a usable fallback
either. The venv doesn't persist between sessions, but the `uv` install is
cheap enough to redo every time without a second thought. CI remains
authoritative for test counts and results regardless.

### Lint and format

```bash
# Lint
ruff check custom_components/ tests/ scripts/

# Format check (does not modify files)
ruff format --check custom_components/ tests/ scripts/

# Fix formatting in-place
ruff format custom_components/ tests/ scripts/
```

Ruff config is in `.ruff.toml` at the repo root. CI runs both `ruff check` and `ruff format --check` on `custom_components/`, `tests/` and `scripts/` — test files get a handful of per-file rule exemptions (no docstring/annotation requirements, `assert` allowed, etc.) but are otherwise held to the same standard as the integration code.

## Upstream compatibility

The table below records the last version of each upstream project that was
reviewed for API changes, breaking changes, and new features relevant to this
integration. Before starting new development work, check for releases newer
than the versions listed here.

| Project | Last reviewed | Where to check |
|---|---|---|
| Home Assistant Core | 2026.3 (minimum); tested against 2026.10.4 (PHCC 0.13.375); 2026.8–2026.10 developer blog and core platform/coordinator source reviewed directly (2026-10-14) — only change needed was the deprecated `async_get_device(identifiers=...)` lookup, now feature-detected (`helpers._device_by_identifier`). Also ready for 2026.11's in-place entity_id renames (`async_entity_id_changed`; guarded by `tests/test_entity_lifecycle.py`). 2026.11.1 source and the contributors blog to 2026-11-10 reviewed (2026-11-09): `DeviceEntry.config_entries` reads now feature-detected (`helpers.device_config_entry_ids`, warned from 2026.10); devices built with `DeviceInfo(...)` (a dataclass from 2026.11, plain dicts to be deprecated); custom integrations may keep returning `bool` from setup; no PHCC for 2026.11 yet, so tests still run on 2026.10.4 | https://github.com/home-assistant/core/releases |
| Dockhand | v1.0.57 (reviewed v1.0.55–v1.0.57 release notes and the routes this integration calls, 2026-11-09. Relevant: 1.0.55 adds `container_start`/`container_stop` schedule types (they get Run now and Enabled entities like other schedules) and makes moved-digest reports configurable, so `pinnedToDigest` can be absent; 1.0.57's new CSRF origin check only applies to cookie-authenticated requests, so bearer-token calls are unaffected. Earlier: v1.0.54 `check-updates` reports a moved digest behind a digest-pinned image as `hasUpdate` plus `pinnedToDigest`; the client clears `hasUpdate` since Install can't apply it, and the update entity shows it as advisory) | https://github.com/Finsys/dockhand/releases |

Update this table after each review session. For the API side of a
Dockhand review, diff `static/openapi.json` between the two release tags
(`git diff v1.0.56 v1.0.57 -- static/openapi.json` in a Dockhand clone):
Dockhand generates it from the `@openapi` comments on its routes, and its
API browser at `/api/docs/ui` on a running Dockhand shows the same. It doesn't describe every
field, so read the route source for exact request and response shapes,
especially for anything that changes or deletes data.

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

## Translations

If a change adds any new user-facing string (a new entity name, a config
option, an error message), add a machine-translated entry for that key
to all locale files in the same change — don't leave it for a follow-up.
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
it; see docs/backlog.md. Any future attempt at `section()` grouping (or
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

## Changelog

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
- **Changes with no user-facing effect** (dependency updates, test or build tooling, CI) get a
  short line under `### Internal` saying what changed and why, so the reasoning is easy to find
  later.
- Each released section is also the GitHub release's notes (CI publishes it, and HACS shows it),
  and `[Unreleased]` is the notes of the current test build. New sections are headed
  `## [X.Y.Z] - YYYY-MM-DD` ([Keep a Changelog](https://keepachangelog.com/)); older ones use an
  em dash, and the tooling reads both.
- **Watch for a specific editing hazard**: a generic search anchor like
  `### Fixed` can match a heading that recurs in multiple version
  sections. Re-check where an edit actually landed, especially after
  inserting near a section boundary.

## Versioning

Semantic versioning, as defined in [semver.md](semver.md). Config-schema changes and downgrade
support follow [architecture.md](architecture.md) §4.

**`dev` holds the expected next version.** When the first change after a release lands on `dev`,
`manifest.json`'s version moves to what that change calls for; a later change that calls for more
raises it. Test builds carry it, and release reviews re-check it. The changelog stays
`[Unreleased]` until the release pull request dates it.

## Branches and releases

| Branch | What goes there | What a push does |
| --- | --- | --- |
| `main` | Releases only: one squash-merged pull request per release. Never pushed to directly. | Releases the version if it has no tag yet; deletes test builds; resets `dev` (sync-dev). |
| `dev` | Adopted work, and Dependabot's updates. `[Unreleased]` is kept current here. | Publishes a test build. |
| `try/<topic>` | Experiments that may be dropped. Branched from `dev`. | Nothing by itself: open a (draft) pull request into `dev` to run CI. |

Don't end a branch name in `tags` (`try/tags`, `try/dockhand-tags`): HACS's downloader removes
every `tags/` from a URL, so HACS validation then reads `hacs.json` from the wrong path and fails.

Adopted `try/` work is squash-merged into `dev`; ideas dropped for good get a line in
[backlog.md](backlog.md).

Day to day:

1. Claude runs `dev`: small, safe changes are committed to it directly; anything else goes on a
   `try/<topic>` branch with a pull request into `dev`, which Claude squash-merges once CI is
   green. Either way the `[Unreleased]` line(s) come with the change and
   `bash scripts/run_tests.sh --full` passes.
2. The owner installs the test build through the Marketplace to try it on a real Home Assistant.
3. `dev` stays releasable: a change that needs the owner's decision first waits on its `try/`
   branch (a draft pull request) until they've seen it.

Releasing (the owner decides when):

1. On a branch from `dev`, run `scripts/bump_version.sh X.Y.Z [YYYY-MM-DD]` with the version
   `dev` already holds (or a different one, if the release review says so): it sets
   `manifest.json`'s version, turns `[Unreleased]` into the dated section (with a fresh empty
   `[Unreleased]` above) and updates the compare links. Go through the release checklist below.
2. Open the release pull request into `main`, titled "Dockhand X.Y.Z", with the new changelog
   section as its body (or open it from `dev` once the bump is merged there).
3. Squash-merge it. CI tags `X.Y.Z` (no leading "v": HACS shows tag names; releases up to 1.11.3 are tagged `vX.Y.Z`), publishes the release with the changelog section as notes and
   `dockhand.zip` attached, deletes the test builds, and resets `dev` to `main`.

HACS installs from that release asset, not the repository's files (`hacs.json`: `zip_release`
and `filename`), so every release and test build must carry `dockhand.zip`, built by
`scripts/release.py package` with the integration's files at the zip's root (HACS extracts it into
`custom_components/dockhand/`). The asset's download count is the install count HACS shows.

No tags are pushed by hand: a version is released exactly once, when its tag doesn't exist yet.
CI refuses a pull request into `main` whose version has no dated changelog section, so an undated
release can't merge (a merge into `main` that releases nothing needs `dev` back on the released
version).

### Release checklist

Part of every release pull request (not needed for everyday pull requests):

- `bash scripts/run_tests.sh --full`: ruff check/format on both `custom_components/` and `tests/`, mypy (strict), the quality scale rule check, and the full test suite with its 100% coverage gate — this now includes `test_config_flow.py`'s whole-tree translation coverage tests (see "Translations"), so a missing/empty key or a locale that's drifted out of sync will already show up as a test failure here, not just at this checklist step
- `manifest.json`: field order correct (`domain`, `name`, then alphabetical)
- `strings.json` and `translations/en.json` are byte-for-byte identical
- Every locale in `translations/` has exactly the same keys as `en.json` (no missing, no extra) — except `api_url`, which stays English everywhere
- Every entity `translation_key` used in code has both a `strings.json` and an `icons.json` entry, and vice versa (no orphans)
- `CHANGELOG.md`: compare-link references at the bottom are correct; re-read the whole release section per "Changelog" above
- Quality scale review, per `docs/quality-scale.md` "Release review": `run_tests.sh --full` already checks the rule list against Home Assistant's current one, strict typing and 100% line coverage; the review covers what those can't — rule requirements that changed, rules this release's additions touch, and `quality_scale.yaml` comments the release made stale. Add a line to that page's review log
- `README.md` matches the current entity list and behavior
- Config flow `CREATE_ENTRY` tests are preceded by whatever `setup_options`/options step they depend on

### What CI does

`.github/workflows/build.yml`, on every push and pull request:

- `python3 scripts/release.py check`: `CHANGELOG.md` has `[Unreleased]`; for pull requests into
  `main` and pushes to `main`, also a dated section for `manifest.json`'s version.
- `ruff check` and `ruff format --check` on `custom_components/`, `tests/` and `scripts/` (ruff
  pinned in `requirements_test.txt`).
- mypy (strict, Home Assistant core's settings in `mypy.ini`) and the full pytest suite on Python
  3.14 with PHCC, with a 100% line coverage gate.
- `scripts/check_quality_scale.py` against Home Assistant's current rule list.
- hassfest and HACS validation.

- `CI passed`: a gate job that passes only when every check above did. It's the one status check
  the `main` ruleset requires, so jobs can change without touching the ruleset.

Then, on a push to `main`, the release and sync-dev jobs; on a push to `dev`, the test build.
Every checkout uses `persist-credentials: false` except sync-dev's, the one job that pushes with
git, so the workflow token isn't left on disk for dependencies' scripts or tests to read.
`tests/test_workflows.py` checks the workflows themselves: permissions on every job, actions
pinned to commit SHAs, no `${{ }}` inside `run:` scripts, no checkout keeping credentials in a job
that doesn't push, and `CI passed` depending on every check job.

### Test builds

Every push to `dev` publishes a GitHub pre-release tagged `v<expected next version>-dev.<run>`
(for example `1.12.0-dev.43` while `dev` holds 1.12.0; right after a release, before `dev` moves
on, `<next patch>-dev.<run>`), so it sorts above the installed release. Its notes are the
`[Unreleased]` section, and its `dockhand.zip` has that version stamped into `manifest.json`, so
Home Assistant and diagnostics show a test build as one (for example `1.11.3-dev.42`). Older
test builds are deleted, so there's only ever one.

To install one: turn on pre-releases for Dockhand, from its **⋮** menu in the Marketplace or with
the **Pre-release** switch entity the Marketplace (or HACS) adds for each repository, disabled by
default (enable it under Settings → Entities; HACS on 2026.10 and older has only the switch). It
then offers the test build as an update. To go back, turn pre-releases off and redownload the
latest release (⋮ → Redownload).

### Repository settings

The owner sets these (sessions can't read most of them):

- **Settings → Rules → Rulesets:** one for `main` (target: the default branch), **enforcement
  Active**: restrict deletions, block force pushes, require a pull request before merging with
  squash as the only allowed method. No required approvals. **Require status checks:**
  `CI passed`. **Require code scanning results:** CodeQL.
- **Settings → General → Pull Requests:** squash merging only; **Automatically delete head
  branches** on.
- **Settings → Branches:** a classic branch protection rule for `dev`: nothing required,
  deletions not allowed (so auto-delete never removes `dev` after a release pull request),
  **force pushes allowed** (sync-dev). A classic rule rather than a ruleset, since a ruleset's
  "Restrict deletions" has been reported not to stop auto-delete.
- The default branch stays `main`.

## Dependencies

Dependabot proposes updates weekly into `dev` (`.github/dependabot.yml`): GitHub Actions (pinned
to full commit SHAs, version in a comment) and the pip pins in `requirements_test.txt`. The
integration itself has no runtime requirements. `pytest-homeassistant-custom-component` pins an
exact Home Assistant release (see "PHCC version ↔ HA version"); `mypy` follows Home Assistant
core's own pin.

## Audits

A "full review" follows the checklist at the top of [audits.md](audits.md), and is recorded
there.

## Licensing

MIT (`LICENSE`).
