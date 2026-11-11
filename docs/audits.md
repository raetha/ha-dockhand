# Audits

Quality, security and housekeeping reviews of the integration, its tests and CI. Repeat when the
owner asks for a full review; record each one below, newest first. The per-release quality scale
review has its own log in [quality-scale.md](quality-scale.md).

## Checklist for a full review

1. **Open pull requests**, Dependabot's especially
   (`gh api "repos/raetha/ha-dockhand/pulls?state=open"`; sessions have the REST API, not GraphQL,
   so `gh pr list` fails). For each: read the diff; check its CI passed
   (`gh api repos/raetha/ha-dockhand/commits/<sha>/check-runs`); for a GitHub Action, check the
   pinned commit is the tag it claims
   (`git ls-remote https://github.com/<owner>/<action> refs/tags/<tag>`); for a pip pin, its
   release notes (PHCC and mypy follow Home Assistant core). Squash-merge good ones into `dev`
   (`gh api -X PUT repos/raetha/ha-dockhand/pulls/<n>/merge -f merge_method=squash`), never into
   `main`. Record any held back, and why.
2. **Security alerts.** Sessions can't read the repository's code scanning, Dependabot or secret
   scanning alerts (403): ask the owner for their titles, and run the checks here: `pip-audit -r
   requirements_test.txt` (test-only; nothing ships), and CodeQL (the bundle from
   `github/codeql-action` releases; `codeql database create --build-mode=none` over a copy of the
   tracked files only, then `database analyze` with the `python-security-and-quality` and
   `actions-security-and-quality` suites).
3. **Tests:** `bash scripts/run_tests.sh --full` (ruff, mypy, quality scale rules, 100% coverage).
4. **Quality scale:** every rule in `quality_scale.yaml` still true of the code
   ([quality-scale.md](quality-scale.md)).
5. **Security of the design:** what the integration exposes (actions that start, stop, update or
   redeploy containers; system container protection), what it validates from Dockhand's API,
   diagnostics safe to post publicly (tokens, TLS keys and Docker label values redacted), nothing
   secret in logs.
6. **Workflows:** `contents: read` at the top, write only on the jobs that release or push;
   actions pinned to commit SHAs; no `${{ }}` expansions inside `run:` scripts; no secrets used on
   pull requests (`tests/test_workflows.py` checks the first three).
7. **Entity model:** re-read Home Assistant's current entity guidance ("State and attributes",
   the entity naming and category pages on developers.home-assistant.io) and walk every entity
   against it and [architecture.md](architecture.md) §12: values that change on their own are
   their own sensors, not attributes; static facts in device info; attributes always present;
   nothing that changes on every poll in an attribute or a recorded state; names from the device,
   not a `name` attribute. Note new guidance in §12, and fix or propose what drifted (renaming a
   `translation_key` breaks the cards, so a conversion changes both repositories together).
8. **Leftovers:** finished experiments, migrations older than the downgrade rule needs
   ([architecture.md](architecture.md) §4), unused code, stale comments and docs (`CLAUDE.md`,
   `docs/development.md`, the README).
9. **Record it:** a dated section below, and changelog lines for anything users notice.

## 2026-11-09: full review before testing 2.0.0

- Open pull requests: none. Every action pin matches its tag and is the latest release; hassfest
  is on master's head. ruff 0.17.3 → 0.17.4. PHCC 0.13.375 (HA 2026.10.4) is still the newest.
- `pip-audit`: only pillow (test-only, through Home Assistant's pin; fixed in 13.0, which HA's
  pin doesn't allow yet). CodeQL (Python, Actions): no security findings; unused names removed,
  the other notes are imports pytest needs or migration constants CodeQL can't see used.
- Home Assistant 2026.11 (source and contributors blog): actions read the deprecated
  `DeviceEntry.config_entries`, logging a warning on 2026.10+; now feature-detected, with a
  regression test (reverted, failed, restored). Device info built with `DeviceInfo(...)` ahead of
  plain dictionaries being deprecated. Follow-ups the owner approved: repair issues linked to their
  config entry where HA supports it (2026.11+). `has_update` (2026.11) isn't needed, but looking at
  it found that HA's version comparison could turn an update entity off for a real newer tag;
  `version_is_newer` now treats any difference as an update, on every supported HA version.
- Repair issues for runtime-change warnings now include the entry id, so two instances can't
  replace each other's.
- `stale.yml` gets `permissions: {}` at the top like `build.yml`'s `contents: read`.
- Tests, ruff, mypy, quality scale rules: pass, 100% coverage. Diagnostics still redact the token,
  labels, TLS keys and Hawser tokens; the event entity carries only the exit code.

## 2026-11-02: moved to the dev/main workflow

- `ci.yml` and `release.yml` replaced by one `build.yml` (changelog check, ruff, mypy, pytest with
  100% coverage, quality scale rules, hassfest, HACS validation; releases created by CI from
  `main`; test builds from `dev`; sync-dev). Every action pinned to a commit SHA, verified against
  its tag with `git ls-remote`; `hassfest` and `hacs/action` were on `@master`/`@main`, `stale.yml`
  on a tag. `tests/test_workflows.py` now requires SHA pins and no expressions in `run:` scripts.
- ruff pinned in `requirements_test.txt` (was unpinned in CI); `scripts/` is linted too.
- Dependabot targets `dev`. No pull requests were open.
