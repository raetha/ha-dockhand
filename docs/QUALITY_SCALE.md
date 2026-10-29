# Quality scale

The integration aims to meet every rule of Home Assistant's
[integration quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
up to and including Platinum. `custom_components/dockhand/quality_scale.yaml`
records each rule's status (`done`, `exempt` or `todo`) and how it's met.

Home Assistant only validates that file for core integrations, and the rules
change over time (new rules are added, existing ones get stricter), so
compliance drifts unless it's checked. This page is how it's kept current.

## What's checked automatically

| Check | Where | Catches |
|---|---|---|
| `scripts/check_quality_scale.py` | CI (`quality-scale` job), `scripts/run_tests.sh --full` | A rule Home Assistant added or retired that `quality_scale.yaml` doesn't match; an unknown status; a `todo`/`exempt` rule with no reason given |
| `mypy` with `mypy.ini` (Home Assistant core's strict settings) | CI (`tests` job), `run_tests.sh --full` | **strict-typing** — including missing `@override` and use of deprecated Home Assistant APIs |
| `pytest --cov-fail-under=100` | CI (`tests` job), `run_tests.sh --full` | Any line no test runs (**test-coverage** itself asks for 95%) |
| hassfest | CI | Manifest, translations, and `quality_scale.yaml` syntax |
| `tests/test_config_flow.py` translation tests | pytest | **entity-translations**, **exception-translations**, **icon-translations** keys out of sync |

`check_quality_scale.py` fetches the rule list from Home Assistant core's
`dev` branch (`script/hassfest/quality_scale.py`, the same list hassfest
uses), so a new rule can fail CI on a commit that didn't touch anything.
That's intended: it's the signal to review the new rule.

## Release review

Part of every release's checklist (`CONTRIBUTING.md`). The automated checks
don't judge whether a rule marked `done` is still really done, so:

1. Run `bash scripts/run_tests.sh --full`. A rule-list failure means a rule
   was added or retired: read its page (below) and add or remove it in
   `quality_scale.yaml`.
2. Read what changed in the rules since the last review:
   `git log --since=<last review date> -- docs/core/integration-quality-scale/`
   in [home-assistant/developers.home-assistant](https://github.com/home-assistant/developers.home-assistant),
   and the "Quality scale" posts on the
   [developer blog](https://developers.home-assistant.io/blog/).
   A rule's requirements can change without its name changing.
3. For anything this release added (an entity, an action, an option, a
   repair issue, a device type), go through the rules it touches — for
   example a new action needs **action-exceptions**, a new option
   **docs-configuration-parameters**, a new entity **entity-translations**,
   **icon-translations**, **entity-category** and
   **entity-disabled-by-default**.
4. Re-read each `quality_scale.yaml` comment the release made stale; they
   describe how the rule is met, so they drift with the code.
5. When Home Assistant core changes its `mypy.ini` `[mypy]` section or the
   mypy version it pins, copy the change into `mypy.ini` and
   `requirements_test.txt`.
6. Record the review below.

Rule pages: `https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/<rule-name>`.

## Notes on rules where the reasoning isn't obvious

- **action-exceptions** — not exempt, even though the integration registers
  no service actions of its own: the rule covers platform actions (pressing
  a button, turning a switch, setting a number, installing an update).
- **parallel-updates** — `0` on the action platforms too. Each action is one
  request to Dockhand, which queues the Docker work itself; see the comment
  in `quality_scale.yaml`.
- **strict-typing** — Home Assistant 2026.10 switched forms to probatio
  (and loads it in place of voluptuous), and moved `BinarySensorDeviceClass`
  to `binary_sensor.const`. The minimum supported version predates both, so
  `config_flow.py` keeps voluptuous behind `_form()`, and the
  `binary_sensor` import carries a `type: ignore`. Both go once the minimum
  reaches 2026.10 (see `docs/BACKLOG.md`).
- **stale-devices** — automatic cleanup deliberately keeps what it can't
  confirm is gone, which is why `async_remove_config_entry_device` exists.
- **discovery**, **discovery-update-info** — exempt: Dockhand advertises
  itself in no way Home Assistant can discover.

## Review log

| Date | Release | Outcome |
|---|---|---|
| 2026-10-29 | 1.11.1 | Bug-fix release; no new entities, actions or options. No rule or developer-blog changes since the 1.11.0 review, and core's `[mypy]` section and mypy pin unchanged. No `quality_scale.yaml` comments made stale. |
| 2026-10-19 | 1.11.0 | Full re-audit against the rules as of Home Assistant 2026.10. Added the new Bronze rules **docs-triggers** and **docs-conditions** (exempt). Fixed **strict-typing**, which was marked done without mypy ever having run: added `mypy.ini` with core's settings and fixed what it found. **action-exceptions** corrected from exempt to done. Added `entity.py` (**common-modules**) and `async_remove_config_entry_device` (**stale-devices**). README gained Use cases, more examples, and Known limitations. Added the automated checks above. Tests brought to 100% line coverage (from about 96%), and the gate raised to match. |
