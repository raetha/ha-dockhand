# Developing Dockhand

The canonical guide for working on this repo. How the integration works and why is in [architecture.md](architecture.md) — **read it before adding any entity, device or config option**, and work through its §5 checklist; ideas already evaluated and set aside are in [backlog.md](backlog.md); what counts as a major, minor or patch change is [semver.md](semver.md) (also the policy ha-dockhand-cards follows); the quality scale process is [quality-scale.md](quality-scale.md); reviews are recorded in [audits.md](audits.md).

## Layout

| Path | What it is |
| --- | --- |
| `custom_components/dockhand/` | The integration: platforms, coordinators, config flow, migrations, translations, `quality_scale.yaml` |
| `tests/` | The full test suite (PHCC), held to the same lint and format standard as the integration |
| `scripts/run_tests.sh` | Runs what CI runs: ruff, mypy, the quality scale rule check, pytest with 100% coverage |
| `scripts/release.py` | Changelog check, release notes, test-build versions and the `dockhand.zip` HACS installs, used by CI |
| `scripts/bump_version.sh` | Prepares a release pull request (version, dated changelog section, compare links) |
| `scripts/check_quality_scale.py` | Compares `quality_scale.yaml` with Home Assistant's current rule list |
| `docs/configuration.md`, `entities.md`, `automations.md`, `data-updates.md`, `troubleshooting.md` | User docs. The README keeps installation, setup and use cases and links here with full `main` URLs, since the Marketplace shows only the README |
| `docs/` | This guide, architecture, backlog, semver policy, quality scale, the runtime-controls design notes, audits |
| `.github/workflows/build.yml` | All of CI: checks, releases, test builds (see "What CI does"); `stale.yml` marks inactive issues |

## Testing

The suite uses [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component) (PHCC): Home Assistant core's own test tooling, pinned to one HA release. Every test imports the integration, which imports `homeassistant`, so all tests need Python 3.14.2+ with PHCC; there's no HA-free subset.

```bash
bash scripts/run_tests.sh                    # ruff, ruff format, AST check (any Python 3; .venv-sandbox)
bash scripts/run_tests.sh --full             # also mypy (strict), the quality scale rule check (fetches HA's rule list) and pytest with 100% coverage (.venv-full)
bash scripts/run_tests.sh --full --venv .venv  # in a given venv
bash scripts/run_tests.sh --full -x -k coord # extra flags go to pytest
```

- **Coverage:** every line of the integration is covered and CI fails on one no test runs (`--cov-fail-under=100`). Add the test with the code. A line that can't be reached can usually be removed; `# pragma: no cover` is for one that must stay, with a comment saying why. `tests/test_platform_setup.py` runs the real setup with every option on and one environment holding a bit of everything: add data there when a new entity's creation path needs covering.
- **PHCC pin:** `requirements_test.txt` tracks the latest stable HA release (Dependabot proposes bumps; find the PHCC version for an HA release on its [releases page](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component/releases)), so tests run against what most users have. The minimum supported HA version is separate, in `hacs.json`.
- **Lint and format:** `.ruff.toml`; CI runs `ruff check` and `ruff format --check` on `custom_components/`, `tests/` and `scripts/`. Tests have a few per-file exemptions (docstrings, annotations, `assert`) and are otherwise held to the same standard.

### Claude sessions

Sessions have no Python 3.14 and building it takes too long, so `uv` fetches a prebuilt one. The preinstalled `uv` is too old (it resolves 3.14 to a release candidate); the upgraded one at `/usr/local/bin/uv` takes precedence:

```bash
pip install --upgrade uv --break-system-packages
/usr/local/bin/uv python install 3.14
/usr/local/bin/uv venv --python 3.14 .venv
/usr/local/bin/uv pip install -r requirements_test.txt --python .venv/bin/python
bash scripts/run_tests.sh --full --venv .venv
```

Docker isn't available (no binary, and the proxy blocks container registries).

## Upstream compatibility

The table below records the last version of each upstream project that was reviewed for API changes, breaking changes, and new features relevant to this integration. Before starting new development work, check for releases newer than the versions listed here.

| Project | Last reviewed | Where to check |
|---|---|---|
| Home Assistant Core | 2026.8 (minimum, from 2.0.0; matches other widely used integrations, and HA 2026.8's entry-scoped device registry calls need no fallback); tested against 2026.10.4 (PHCC 0.13.375); 2026.8–2026.10 developer blog and core platform/coordinator source reviewed directly (2026-10-14) — only change needed was the deprecated `async_get_device(identifiers=...)` lookup, now the entry-scoped `async_get_device_by_identifier` (`helpers._device_by_identifier`). Also ready for 2026.11's in-place entity_id renames (`async_entity_id_changed`; guarded by `tests/test_entity_lifecycle.py`). 2026.11.1 source and the contributors blog to 2026-11-10 reviewed (2026-11-09): `DeviceEntry.config_entries` (warned from 2026.10) no longer read: devices are looked up per entry and services use `DeviceEntry.config_entry_id`; devices built with `DeviceInfo(...)` (a dataclass from 2026.11, plain dicts to be deprecated); custom integrations may keep returning `bool` from setup; no PHCC for 2026.11 yet, so tests still run on 2026.10.4 | https://github.com/home-assistant/core/releases |
| Dockhand | v1.0.57 (reviewed v1.0.55–v1.0.57 release notes and the routes this integration calls, 2026-11-09. Relevant: 1.0.55 adds `container_start`/`container_stop` schedule types (they get Run now and Enabled entities like other schedules) and makes moved-digest reports configurable, so `pinnedToDigest` can be absent; 1.0.57's new CSRF origin check only applies to cookie-authenticated requests, so bearer-token calls are unaffected. Earlier: v1.0.54 `check-updates` reports a moved digest behind a digest-pinned image as `hasUpdate` plus `pinnedToDigest`; the client clears `hasUpdate` since Install can't apply it, and the update entity shows it as advisory) | https://github.com/Finsys/dockhand/releases |

Update this table after each review session. For the API side of a Dockhand review, diff `static/openapi.json` between the two release tags (`git diff v1.0.56 v1.0.57 -- static/openapi.json` in a Dockhand clone): Dockhand generates it from the `@openapi` comments on its routes, and its API browser at `/api/docs/ui` on a running Dockhand shows the same. It doesn't describe every field, so read the route source for exact request and response shapes, especially for anything that changes or deletes data.

## Code style

- **Comments explain why:** a non-obvious constraint, a tradeoff, why not the obvious approach. Not what the code says, not how a bug was found, not how an earlier version behaved (that's the changelog and git history).
- **Logic shared by platform files goes in `helpers.py`, never a second copy,** however small. Copies drift: a fix applied to the obvious copies misses the one written differently. `_coordinator_env()`, `already_registered()`, `_find_container()` and `_find_stack()` are that move. This is about logic, not naming: renaming variables for uniformity is churn.

## Translations

Every new user-facing string (an entity name, an option, an error) gets a machine-translated entry in every locale in the same change. `strings.json` and `translations/en.json` stay byte-for-byte identical, and every locale has exactly the same keys except `api_url`, which stays English everywhere.

`test_config_flow.py` enforces this over the whole tree: no empty values, `en.json` identical to `strings.json`, every locale covering every key, and every field of the options schema (`_options_schema()`, used by both `config.step.setup_options` and `options.step.init`) labelled and described in both places. What tests can't show is how the frontend renders a form: an attempt to group options with `section()` once showed raw keys in a real HA under two translation layouts, though the tests passed (see backlog.md). Layout changes to a form need a look in a real Home Assistant.

The integration ships machine-generated translations:

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

`CHANGELOG.md`'s `[Unreleased]` section is release notes for end users, not a development log. A few rules that keep it that way:

- **One line per paragraph or list item**, in every Markdown file: the renderer wraps it. GitHub's release pages turn each line break into a visible one, so wrapped source shows as ragged release notes. CI checks it (`scripts/markdown.py --check`; without `--check` it joins the lines).
- **Open with a summary.** A few sentences under the version heading, before the first `###` section, saying why the release matters: its aims or highlights, and what to do before upgrading if anything is breaking. The sections below it carry the details. It's part of the release notes CI publishes, so keep it for people installing, and rewrite it as the release takes shape; a small release may need only a sentence.
- **Never edit an already-released section** (anything with a version number and date below `[Unreleased]`); CI compares them with `main`'s. Those entries describe how that version worked at the time; a later change gets its own new entry in `[Unreleased]`, not a retroactive edit to history.
- **Describe the net difference for a user, not the journey.** If a bug was introduced and fixed within the same unreleased cycle — code that was only ever in development builds, never a release — don't add a "Fixed" entry narrating it. Just write the final `Added`/`Changed` entry as if the feature always worked that way; there's nothing to disclose about something that never shipped broken. Legitimate `Fixed` entries are only for bugs in already-released behavior. The same applies to a sub-aspect of an entirely new feature: if an entity is new this cycle, a detail of how it behaves (e.g. it dynamically relabels itself) is part of describing the new entity, not a separate `Changed` entry saying it "now" does something — there's no prior released state to contrast against.
- **Cut implementation detail.** API endpoints touched, which coordinator, internal architecture, migration mechanics — all useful in a commit message or code comment, not here. Focus on what a user actually notices: a new entity, a renamed setting, a behavior change.
- **Before a release, re-read the whole `[Unreleased]` section top to bottom** and cut anything that reads like an engineering journal rather than release notes.
- **Changes with no user-facing effect** (dependency updates, test or build tooling, CI) get a short line under `### Internal` saying what changed and why, so the reasoning is easy to find later.
- Each released section is also the GitHub release's notes (CI publishes it, and HACS shows it), and `[Unreleased]` is the notes of the current test build. New sections are headed `## [X.Y.Z] - YYYY-MM-DD` ([Keep a Changelog](https://keepachangelog.com/)); older ones use an em dash, and the tooling reads both.
- **Watch for a specific editing hazard**: a generic search anchor like `### Fixed` can match a heading that recurs in multiple version sections. Re-check where an edit actually landed, especially after inserting near a section boundary.

## Versioning

Semantic versioning, as defined in [semver.md](semver.md). Config-schema changes and downgrade support follow [architecture.md](architecture.md) §4.

**`dev` holds the expected next version.** When the first change after a release lands on `dev`, `manifest.json`'s version moves to what that change calls for; a later change that calls for more raises it. Test builds carry it, and release reviews re-check it. The changelog stays `[Unreleased]` until the release pull request dates it.

## Branches and releases

| Branch | What goes there | What a push does |
| --- | --- | --- |
| `main` | Releases only: one squash-merged pull request per release. Never pushed to directly. | Releases the version if it has no tag yet; deletes test builds; resets `dev` (sync-dev). |
| `dev` | Adopted work, and Dependabot's updates. `[Unreleased]` is kept current here. | Publishes a test build. |
| `try/<topic>` | Experiments that may be dropped. Branched from `dev`. | Nothing by itself: open a (draft) pull request into `dev` to run CI. |

Don't end a branch name in `tags` (`try/tags`, `try/dockhand-tags`): HACS's downloader removes every `tags/` from a URL, so HACS validation then reads `hacs.json` from the wrong path and fails.

Adopted `try/` work is squash-merged into `dev`; ideas dropped for good get a line in [backlog.md](backlog.md).

Day to day:

1. Claude runs `dev`: small, safe changes are committed to it directly; anything else goes on a `try/<topic>` branch with a pull request into `dev`, which Claude squash-merges once CI is green. Either way the `[Unreleased]` line(s) come with the change and `bash scripts/run_tests.sh --full` passes.
2. The owner installs the test build through the Marketplace to try it on a real Home Assistant.
3. `dev` stays releasable: a change that needs the owner's decision first waits on its `try/` branch (a draft pull request) until they've seen it.

Releasing (the owner decides when):

1. On a branch from `dev`, run `scripts/bump_version.sh X.Y.Z [YYYY-MM-DD]` with the version `dev` already holds (or a different one, if the release review says so): it sets `manifest.json`'s version, turns `[Unreleased]` into the dated section (with a fresh empty `[Unreleased]` above) and updates the compare links. Go through the release checklist below.
2. Open the release pull request into `main`, titled "Dockhand X.Y.Z", with the new changelog section as its body (or open it from `dev` once the bump is merged there).
3. Squash-merge it. CI tags `X.Y.Z` (no leading "v": HACS shows tag names; releases up to 1.11.3 are tagged `vX.Y.Z`), publishes the release with the changelog section as notes and `dockhand.zip` attached, deletes the test builds, and resets `dev` to `main`.

HACS installs from that release asset, not the repository's files (`hacs.json`: `zip_release` and `filename`), so every release and test build must carry `dockhand.zip`, built by `scripts/release.py package` with the integration's files at the zip's root (HACS extracts it into `custom_components/dockhand/`). The asset's download count is the install count HACS shows.

No tags are pushed by hand: a version is released exactly once, when its tag doesn't exist yet. CI refuses a pull request into `main` whose version has no dated changelog section, so an undated release can't merge (a merge into `main` that releases nothing needs `dev` back on the released version).

### Release checklist

Part of every release pull request (not needed for everyday pull requests):

- `bash scripts/run_tests.sh --full` passes (it covers the translation rules in "Translations")
- `manifest.json`: field order correct (`domain`, `name`, then alphabetical)
- Every entity `translation_key` used in code has both a `strings.json` and an `icons.json` entry, and vice versa (no orphans)
- `CHANGELOG.md`: compare-link references at the bottom are correct; re-read the whole release section per "Changelog" above
- Quality scale review, per `docs/quality-scale.md` "Release review": `run_tests.sh --full` already checks the rule list against Home Assistant's current one, strict typing and 100% line coverage; the review covers what those can't — rule requirements that changed, rules this release's additions touch, and `quality_scale.yaml` comments the release made stale. Add a line to that page's review log
- `README.md` and the user docs it links to (`docs/configuration.md`, `entities.md`, `automations.md`, `data-updates.md`, `troubleshooting.md`) match the current entities and behavior
- Config flow `CREATE_ENTRY` tests are preceded by whatever `setup_options`/options step they depend on

### What CI does

`.github/workflows/build.yml`, on every push and pull request:

- `python3 scripts/release.py check`: `CHANGELOG.md` has `[Unreleased]`; for pull requests into `main` and pushes to `main`, also a dated section for `manifest.json`'s version.
- `ruff check` and `ruff format --check` on `custom_components/`, `tests/` and `scripts/` (ruff pinned in `requirements_test.txt`).
- mypy (strict, Home Assistant core's settings in `mypy.ini`) and the full pytest suite on Python 3.14 with PHCC, with a 100% line coverage gate.
- `scripts/check_quality_scale.py` against Home Assistant's current rule list.
- hassfest and HACS validation.

- `CI passed`: a gate job that passes only when every check above did. It's the one status check the `main` ruleset requires, so jobs can change without touching the ruleset.

Then, on a push to `main`, the release and sync-dev jobs; on a push to `dev`, the test build. Every checkout uses `persist-credentials: false` except sync-dev's, the one job that pushes with git, so the workflow token isn't left on disk for dependencies' scripts or tests to read. `tests/test_workflows.py` checks the workflows themselves: permissions on every job, actions pinned to commit SHAs, no `${{ }}` inside `run:` scripts, no checkout keeping credentials in a job that doesn't push, and `CI passed` depending on every check job.

### Test builds

Every push to `dev` publishes a GitHub pre-release tagged `<expected next version>-dev.<run>` (for example `2.0.0-dev.85` while `dev` holds 2.0.0; right after a release, before `dev` moves on, `<next patch>-dev.<run>`), so it sorts above the installed release. Its notes are the `[Unreleased]` section, and its `dockhand.zip` has that version stamped into `manifest.json`, so Home Assistant and diagnostics show a test build as one. Older test builds are deleted, so there's only ever one.

To install one: turn on pre-releases for Dockhand, from its **⋮** menu in the Marketplace or with the **Pre-release** switch entity the Marketplace (or HACS) adds for each repository, disabled by default (enable it under Settings → Entities; HACS on 2026.10 and older has only the switch). It then offers the test build as an update. To go back, turn pre-releases off and redownload the latest release (⋮ → Redownload).

### Repository settings

The owner sets these (sessions can't read most of them):

- **Settings → Rules → Rulesets:** one for `main` (target: the default branch), **enforcement Active**: restrict deletions, block force pushes, require a pull request before merging with squash as the only allowed method. No required approvals. **Require status checks:** `CI passed`. **Require code scanning results:** CodeQL.
- **Settings → General → Pull Requests:** squash merging only; **Automatically delete head branches** on.
- **Settings → Branches:** a classic branch protection rule for `dev`: nothing required, deletions not allowed (so auto-delete never removes `dev` after a release pull request), **force pushes allowed** (sync-dev). A classic rule rather than a ruleset, since a ruleset's "Restrict deletions" has been reported not to stop auto-delete.
- The default branch stays `main`.

## Dependencies

Dependabot proposes updates weekly into `dev` (`.github/dependabot.yml`): GitHub Actions (pinned to full commit SHAs, version in a comment) and the pip pins in `requirements_test.txt`. The integration itself has no runtime requirements. `pytest-homeassistant-custom-component` pins an exact Home Assistant release (see "Testing"); `mypy` follows Home Assistant core's own pin.

## Audits

A "full review" follows the checklist at the top of [audits.md](audits.md), and is recorded there.

## Licensing

MIT (`LICENSE`).
