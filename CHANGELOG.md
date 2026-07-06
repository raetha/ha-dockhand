# Changelog

## [Unreleased]

## [1.7.4] — 2026-07-06

### Fixed

- **Health sensor now appears without a restart when a container gains a
  healthcheck** — previously, if a container was recreated from an image
  that added a `HEALTHCHECK` instruction after the integration was set up,
  its Health sensor was not created until Home Assistant restarted or the
  integration was reloaded.

- **Duplicate Docker hosts get complete network entities** — when two
  environments point at the same Docker host (e.g. a direct connection and
  a Hawser agent during migration), they report identical network IDs.
  Network entities were previously only created for the first environment
  seen; each environment now gets its own set.

### Changed

- **Poll intervals now enforce minimum values** — the options flow rejects
  intervals below 10 s (fast), 30 s (slow), and 300 s (update checks).
  Zero or negative values previously caused the coordinator to refresh in
  a tight loop, hammering the Dockhand API. Existing stored values are
  unaffected until the options form is next submitted.

- **Diagnostics redact container and image labels** — Docker labels can
  carry secrets (e.g. reverse-proxy basic-auth hashes), and diagnostics
  are commonly attached to public bug reports. The compose-vs-freestanding
  summary counts are unaffected.

### Internal

- `bump_version.sh` now inserts the dated release heading beneath
  `## [Unreleased]` (so drafted notes become the release notes) and
  maintains the compare links at the bottom of this file automatically.
  Previously it prepended an unbracketed heading above `[Unreleased]`,
  which is how earlier releases ended up with `— TBD` headings. It also
  no longer requires a clean working tree — the version bump can be
  committed together with the release's other changes in a single commit
  (a warning is printed if `manifest.json` or `CHANGELOG.md` themselves
  have uncommitted edits, since the script rewrites both).
- Removed hardcoded test counts from `quality_scale.yaml` and hardcoded
  HA versions from `run_tests.sh` — CI and `requirements_test.txt` are
  authoritative.

## [1.7.3] — 2026-06-23

### Fixed

- **Multiple Dockhand instances now supported** — entity unique IDs were
  previously scoped only to environment and container name, causing collisions
  when two Dockhand integrations shared the same environment or container
  names (e.g. both having an environment `1` with a container named
  `dockhand`). Unique IDs are now prefixed with the config entry ID, making
  them globally unique regardless of how many Dockhand instances are
  configured. Closes #14.

  **Automatic migration:** existing installations are migrated automatically
  on first startup after upgrade. No manual action is required for single-
  instance users. Users with multiple Dockhand instances configured
  simultaneously should reduce to one instance before upgrading, then add
  the others back afterward.

### Internal

- Unique ID format changed from `dockhand_{type}_{env_id}_{discriminator}`
  to `{entry_id}_{env_id}_{type}_{discriminator}`, placing the config entry
  ID first and the environment ID before the object type for a consistent
  instance → environment → object hierarchy.

## [1.7.2] — TBD

### Changed

- **Update entity ID simplified** — update entity IDs no longer include the
  `_image_update` suffix (e.g. `update.myenv_containers_mycontainer` instead
  of `update.myenv_containers_mycontainer_image_update`). This aligns with
  the standard HA pattern for devices that have a single update entity, used
  by ESPHome, UniFi, and others. **Action required:** if you reference the
  old entity ID in automations, dashboards, or scripts, update them after
  upgrading. HA will show the old entity as unavailable until reassigned; use
  **Settings → Devices & Services → Entities** to find and update references.

- **Update warning styling** — warnings in the update entity release notes
  (vulnerability scanner notice, system container notice, updates-disabled
  notice) now use the native `<ha-alert>` component instead of plain emoji
  text, matching the visual style used by HACS and other integrations. The
  scanner and system container warnings use `warning` style; the
  updates-disabled notice uses `info` style. The `release_summary` field is
  no longer populated (consistent with HACS).

### Internal

- **Migration functions extracted to `migration.py`** — the two one-time
  registry migration functions (introduced in 1.4.1 and 1.5.0) have been
  moved from `__init__.py` into a dedicated `migration.py` module. Functions
  are now named by the version they target (`migrate_1_4_0_*`,
  `migrate_1_5_0_*`) to make future retirement straightforward. No behaviour
  change.

- **Test suite converted to pure pytest** — `test_api.py`, `test_entities.py`,
  and `test_workflows.py` have been converted from `unittest.TestCase` to
  standard pytest functions and fixtures, consistent with the rest of the
  suite. Test count unchanged at 356.

### Documentation

- Added guidance to the README on how to exclude containers from HA using
  the existing `dockhand.hidden=true` Docker label, HA's device disable
  feature, and bulk device selection for larger installs.

## [1.7.1] — 2026-06-05

### Fixed

- **Container update timeout too short** — the `batch-update` API call used the
  same 30-second timeout as read endpoints. A pull-and-recreate can take
  considerably longer for large images or slow connections, causing HA to report
  failure even when Dockhand completed the update successfully (Fixes #11).
  The timeout for this operation is now 300 seconds.
- **Update action errors not logged** — when `async_install` raised a
  `HomeAssistantError` the underlying exception was only surfaced in the HA
  frontend string, not in the log. The full exception type and message are now
  logged at `ERROR` level, making timeout vs. API error vs. network failure
  distinguishable from the HA log.
- **Container stat sensor icons missing** — the eight container resource sensors
  added in 1.7.0 (CPU %, memory usage/percent/limit, network rx/tx, disk
  read/write) were not assigned icons in `icons.json`. They now have distinct
  icons matching their environment-level counterparts.
- **Reconfigure flow corrected** — the Reconfigure step now shows only
  connection settings (URL, SSL, API token), matching standard HA convention.
  Previously it duplicated the full options form including poll intervals and
  feature flags, which belong in **Configure** instead.
- **API token missing from Reconfigure** — users can now update, rotate, or
  clear their API token directly from the Reconfigure step without needing to
  delete and re-add the integration. The token field is pre-populated and
  masked — clear it to disable authentication (you will be prompted again if
  the server still requires it), or enter a new value to rotate credentials.
- **API token fields masked** — token entry fields across all flow steps now
  render as password inputs, preventing shoulder-surfing and accidental exposure
  of credentials in screenshots.
- **Options step added to initial setup** — poll intervals and optional feature
  flags (schedules, images, volumes, networks, container updates) are now
  presented as step 3 of the setup wizard, so new users can configure everything
  without needing to find the Configure button afterwards. Options are stored in
  `entry.options` from the start, consistent with the existing Configure flow.

## [1.7.0] — 2026-06-01

### Added

- **Container resource stats sensors** — eight new diagnostic sensors are now
  created for every container, all disabled by default. Enable only the ones
  you care about; enabled/disabled state survives container recreation
  (entity registry is keyed on `env_id` + container name, both stable).
  - **CPU usage** (`%`) — current CPU as a percentage of total host capacity
  - **Memory usage** (bytes, displayed in MiB) — effective memory in use
    (cache excluded); includes `memory_cache_bytes` as a state attribute
  - **Memory usage %** — memory used relative to the configured limit (or host
    RAM when no limit is set)
  - **Memory limit** (bytes, displayed in MiB) — configured container memory
    limit, or host RAM when unconstrained; useful when explicit limits are set
  - **Network in / Network out** (bytes, displayed in MiB) — cumulative bytes
    received/transmitted; resets to zero on container restart
    (`TOTAL_INCREASING` state class)
  - **Disk read / Disk write** (bytes, displayed in MiB) — cumulative block
    I/O; resets on restart (`TOTAL_INCREASING` state class)

  Stats are fetched via a single bulk API call per environment
  (`GET /api/containers/stats?env=N`) on every fast-coordinator cycle (60 s
  default), rather than one call per container. Stopped, exited, or created
  containers are absent from the stats response and show as unavailable until
  running again.

  Resolves https://github.com/raetha/ha-dockhand/issues/10

### Maintenance

- Migrate test suite from `ha_stubs.py` to `pytest-homeassistant-custom-component`
  (PHCC 0.13.333, pinned to HA 2026.5.4). Eliminates 700-line hand-rolled stub
  layer; all tests now run against real HA internals. `test_api.py` and
  `test_workflows.py` remain HA-independent unit tests runnable anywhere.
  `pytest.ini` updated with `asyncio_mode = auto`. Full suite requires Python
  3.14.2+ — run locally via `pytest tests/` in a PHCC venv (see
  `docs/development.md`), or rely on CI for authoritative results.

## [1.6.0] — 2026-05-22

> **Action recommended for all existing users:** After upgrading to 1.6.0,
> go to **Settings → Entities**, filter by the Dockhand integration, select
> all entities, open the **⋮ menu**, and choose **"Recreate entity IDs of
> selected"**. This refreshes all entity_ids to the new naming convention
> (see *Entity naming redesign* below). Without this step, new entities
> (e.g. from new containers or stacks) will use the new convention while
> existing entities keep their old ids, causing inconsistency.
>
> **Note:** Recreating entity_ids will temporarily break any dashboards,
> automations, or templates that reference the old entity_ids. Update those
> references after running the recreate step. The change is a one-time
> migration — entity_ids are stable after this point.

**Additional breaking changes** — see full notes below.

### Migration

**Container image sensor removed.** If you had manually enabled the per-container
`Image` sensor (disabled by default), it will disappear after upgrading. The same
value is available as the `image` attribute on the container's `State` sensor:

```yaml
{{ state_attr('sensor.mycontainer_state', 'image') }}
```

**Container health sensor now enabled by default.** Containers with a Docker
healthcheck configured will now have their `Health` sensor enabled. Note: if
you upgraded from an earlier version, already-registered health sensors will
not be auto-enabled — enable them once manually in Settings → Entities. New
installations and new containers will have the sensor enabled automatically.

**Activity events sensor state class changed.** Changed from `TOTAL_INCREASING`
to `MEASUREMENT` (disabled by default). Existing long-term statistics may show
a chart discontinuity at the upgrade point.

**Restart button entity_ids renamed** ([#8](https://github.com/raetha/ha-dockhand/issues/8)).
Container restart buttons are now `button.<env>_containers_<name>_restart` and
stack restart buttons are `button.<env>_stacks_<name>_restart`. See **Entity
naming redesign** below for full details and migration instructions.

### Entity naming redesign ([#8](https://github.com/raetha/ha-dockhand/issues/8))

All container, stack, image, network, and volume entity_ids now include the
object type as a segment, making them unambiguous without looking up which
device they belong to.

**New convention: `<platform>.<env>_<type>_<name>_<attribute>`**

| Entity | Old entity_id | New entity_id |
|---|---|---|
| Container state | `sensor.myenv_mycontainer_state` | `sensor.myenv_containers_mycontainer_state` |
| Container health | `sensor.myenv_mycontainer_health` | `sensor.myenv_containers_mycontainer_health` |
| Container switch | `switch.myenv_mycontainer` | `switch.myenv_containers_mycontainer` |
| Container restart | `button.myenv_mycontainer_restart` | `button.myenv_containers_mycontainer_restart` |
| Container update | `update.myenv_mycontainer_image_update` | `update.myenv_containers_mycontainer_image_update` |
| Stack status | `sensor.myenv_mystack_status` | `sensor.myenv_stacks_mystack_status` |
| Stack count | `sensor.myenv_mystack_containers` | `sensor.myenv_stacks_mystack_containers` |
| Stack switch | `switch.myenv_mystack` | `switch.myenv_stacks_mystack` |
| Stack restart | `button.myenv_mystack_restart` | `button.myenv_stacks_mystack_restart` |
| Image | `sensor.mycontainer` | `sensor.myenv_images_mycontainer` |
| Network | `sensor.mynetwork` | `sensor.myenv_networks_mynetwork` |
| Volume | `sensor.myvolume` | `sensor.myenv_volumes_myvolume` |

Env-level entities (CPU, memory, container count, etc.) and schedule entities
are unchanged.

**What drives the change:** Container and stack devices are now named
`""{Env} – Containers – {name}""` and `"{Env} – Stacks – {name}"`. HA slugifies
these device names to form the entity_id prefix. Image/network/volume sensors
now use `has_entity_name = True` so their group device names
(`"{Env} – Images"`, etc.) prefix their entity_ids. Container and stack switches
are now primary entities with no name suffix — the device name carries full
context (`switch.myenv_containers_mycontainer` rather than
`switch.myenv_mycontainer`), following HA convention for the principal
on/off entity of a device.

**Migration:** Entity_ids are not automatically migrated — unique_ids are stable
so no data is lost. To refresh entity_ids to the new convention: go to
**Settings → Entities**, filter by the Dockhand integration, select all
entities, open the **⋮ menu**, and choose **"Recreate entity IDs of selected"**.
Update any automations or templates that reference old entity_ids after the
refresh.

### Changed

- **Device registration consolidated.** All `async_get_or_create` calls
  previously duplicated between `__init__.py` and `sensor.py` are now
  exclusively in `helpers.py` via `_ensure_env_devices` and
  `_ensure_hub_devices`. A side-effect of the duplication was the
  environment hub device being registered without `entry_type=SERVICE` in one
  path, causing it to appear as physical hardware in the HA device registry.
- **Compose label check centralised.** The inline `com.docker.compose.project`
  label extraction appeared in six places across five files. Replaced with a
  single `_compose_project(container)` helper in `helpers.py`.
- **Container health sensor** is now enabled by default. It is only ever created
  when the container has a Docker healthcheck, so it is never
  permanently unavailable.
- **Containers group device** (`<Environment> – Containers`) is now removed when
  all containers in an online environment are Compose-managed. Previously the
  empty group device persisted indefinitely.
- `docs/device_class_matrix.md` fully updated: correct model names, all entity
  types, enabled/disabled defaults, three-coordinator architecture.

### Fixed

- **Action exception handling:** all action methods in `button.py`, `switch.py`,
  and `update.py` now raise `HomeAssistantError` with a translatable message on
  failure. Previously, raw API exceptions propagated unhandled. Two exception
  translation keys added to `strings.json`: `action_failed` and
  `container_not_found`.
- **Environment deletion left container and stack devices orphaned**
  ([#9](https://github.com/raetha/ha-dockhand/issues/9)). When a Dockhand
  environment was deleted, the env hub and group devices were correctly removed
  but container and stack child devices and their entities were left behind. The
  cleanup guard `env_id in online_env_ids` evaluated to false for deleted
  environments (which are absent from both `env_ids` and `online_env_ids`), so
  cleanup was skipped. The fix checks `env_id not in env_ids` first (deleted →
  remove unconditionally) before applying the offline guard (exists but offline →
  preserve). The same two-case logic is applied to image, network, volume, and
  update entity cleanup, and the `slow_valid` guard no longer blocks
  deleted-environment entity removal.
- **Restart button entity_id collision when container and stack share a name**
  ([#8](https://github.com/raetha/ha-dockhand/issues/8)). When a container and
  stack shared the same name, both restart buttons produced the same entity_id
  (e.g. `button.myenv_mycontainer_restart` for both), with HA assigning `_2` to
  the second. Resolved by the entity naming redesign — container and stack devices
  now carry the type in their name (`myenv – Containers – mycontainer` vs
  `myenv – Stacks – mycontainer`), so the entity_ids are inherently distinct
  (`button.myenv_containers_mycontainer_restart` vs
  `button.myenv_stacks_mycontainer_restart`) without any translation key changes.
- **Activity events sensor** used `TOTAL_INCREASING`, causing HA to log errors
  when the Docker daemon restarted and the event count reset. Changed to
  `MEASUREMENT`.
- **Schedule device naming.** Schedule devices were previously named only by
  their task name, so they did not group together visually in the HA device
  list. Now named `"Dockhand – Schedules – {task name}"` so all schedule
  devices sort and group together. Entity_ids become
  `sensor.dockhand_schedules_{name}_next_run` etc. HA intentionally displays
  the integration icon for all update entities — custom icon entries have no
  effect and are contrary to HA quality scale guidance.
- `icons.json` was missing an entry for the `check_updates` button. Added
  `mdi:cloud-search`.
- Five sensor classes had docstrings placed after a class attribute, so Python
  did not treat them as class docstrings. Corrected.
- README: model names in device diagram corrected (`Container`, `Stack`);
  stale credential wording removed; `dockhand.hidden=true` container note added;
  `Health` entity description updated.

### Removed

- **Container image sensor** (`DockhandContainerImageSensor`). The image name
  is already the `image` attribute on each container's `State` sensor.
- Dead helpers `_container_group_device()` and `_stack_group_device()` from
  `helpers.py` (defined but never called).
- `image` translation key from `strings.json`, all translation files, and
  `icons.json`.

### Tests

- `test_entities.py` refactored: 8 classes → 15, 89 tests → 119. Logically
  unrelated tests moved out of `TestSlowSensors` into their own classes.
- New coverage: `HomeAssistantError` propagation for all action methods,
  `_compose_project` helper (6 cases), `_container_has_healthcheck` (7 cases),
  container state `image` attribute, stack status `container_count` attribute.
- Test count: 222 → 254.

## [1.5.1] — 2026-05-19

### Fixed

- Container devices, sensors, switches, and buttons now persist across image
  updates and container recreation. Container devices previously used the
  Docker hash ID as their identifier — this changed on every container
  recreation, removing all container entities and losing historical data,
  automation history, and area assignments. Devices are now keyed on
  `container_{env_id}_{name}`, which is stable. Docker enforces unique
  container names per host, making this a safe key.
- Update entities no longer disappear after triggering an image update. With
  container devices now name-based and stable, update entities correctly
  remain attached to their container device across recreation.
- All API calls that act on a container (start, stop, restart, update) now
  look up the current container ID from coordinator data at call time, rather
  than using the ID stored at entity creation time.
- Automatic migration of existing container device identifiers and entity
  unique_ids from all pre-1.5.1 formats. No manual action required.

## [1.5.0] — 2026-05-15

### Added

- Container device identifiers now include the environment ID
  (`container_{env_id}_{docker_hash}`), enabling precise per-environment
  cleanup. Previously the identifier was `container_{docker_hash}` with no
  env scoping, which required a conservative "any env offline = skip all
  container cleanup" rule. Now only containers belonging to an offline
  environment are protected — containers on other online environments are
  cleaned up normally.
- Automatic migration of existing container device identifiers from the old
  format to the new format on first load. No manual action required.
- Update entity release notes now display in full via HA's more-info dialog.
  The `release_summary` attribute has a 255-character limit; all content is
  now in `async_release_notes` (full Markdown, no length limit) with a brief
  one-liner kept in `release_summary`.

### Fixed

- Schedule devices and entities are no longer removed ~60 seconds after a
  reload or HA restart. Two bugs: (1) the live set used `schedule_{id}` as
  the device identifier, but devices are registered as `schedule_{id}_{type}`
  — so every schedule always appeared stale; (2) when `enable_schedules=False`,
  the empty schedule list was treated as "all schedules deleted."
- Container, stack, image, network, volume, and update entities are no longer
  removed when a Docker host is temporarily offline (e.g. during a reboot).
  The fix checks the `online` field from each environment's dashboard stats
  and skips cleanup for any offline environment. Permanently deleting an
  environment from Dockhand still triggers a full cleanup.
- The `schedules_hub` device is now removed when `enable_schedules` is
  disabled, closing a cleanup gap where it had no removal path.

### Changed

- Removed legacy network and volume *device* cleanup code that handled
  pre-1.2.0 installs.

## [1.4.1] — 2026-05-08

### Fixed

- Update entities no longer disappear after triggering an image update.
  Container IDs (Docker hashes) change on every container recreation, so
  update entities keyed on container ID were removed by the cleanup routine
  after each update. Entity identity is now keyed on `(env_id,
  container_name)` which is stable across recreation.
- Update entity unique_ids are automatically migrated from the 1.4.0
  container-ID-based scheme on first load.

### Added

- Update entities display a warning when vulnerability scanning is enabled on
  the environment. The `batch-update` API endpoint does not apply scanning —
  that workflow is only available through the Dockhand UI.

## [1.4.0] — 2026-05-06

### Added

- **Container update entities** — an optional `update` platform adds one
  [`UpdateEntity`](https://developers.home-assistant.io/docs/core/entity/update/)
  per container. Enable via **Configure → Enable container update entities**.
  - Update availability is checked on a configurable interval (default 24 h)
    via `POST /api/containers/check-updates`
  - Installed and latest versions shown as short digest hashes
  - **Install** triggers a pull-and-recreate via `batch-update`. Note:
    vulnerability scanning is not applied by this endpoint
  - Install is suppressed for system containers and containers with the
    `dockhand.update=false` label
- **"Check for image updates" button** on each environment device, for
  on-demand update checks without waiting for the scheduled poll.

### Fixed

- Entity names now correctly use translated strings in all supported languages.
  26 entity classes had a hardcoded `_attr_name` overriding the translation
  system, so non-English users always saw English names.

### Changed

- Dashboard stats are now fetched in a single `GET /api/dashboard/stats` call
  per poll cycle instead of one call per environment.
- Registry cleanup consolidated into a single function covering all resource
  types, replacing three separate functions with inconsistent guard logic.
  Environment, group, and schedule devices are now properly removed when
  permanently deleted from Dockhand.
- The update coordinator reuses the fast coordinator's environment list
  instead of making a redundant `GET /api/environments` call.

## [1.3.1] — 2026-05-03

### Changed

- Storage sensors now use bytes as the native unit. `Containers disk usage`
  and `Build cache size` previously converted to MiB before storing. They now
  store the raw byte value with `suggested_unit_of_measurement = MiB`, letting
  HA handle display conversion and allowing users to change the unit per-entity.
  **Note:** automations comparing raw sensor state values in MiB need updating
  to use byte values.

### Fixed

- CPU usage sensor reported values up to 100× too high. `cpuPercent` from the
  API is already a percentage; the sensor was incorrectly multiplying by 100.

## [1.3.0] — 2026-05-01

### Added

- Machine-generated translations for 10 languages: German, Spanish, French,
  Italian, Norwegian Bokmål, Dutch, Polish, Portuguese, Swedish, and
  Simplified Chinese. All translatable strings are covered.
- `CONTRIBUTING.md` with guidance for correcting translations and submitting
  new languages.

## [1.2.0] — 2026-04-28

**Breaking change** — session-cookie authentication has been removed. The
integration now uses Dockhand API tokens exclusively.

Requires **Dockhand ≥ 1.0.26**.

### Migration

Existing installations will be flagged for re-authentication on the next HA
restart. Go to **Settings → Devices & Services → Dockhand →
Re-authenticate**, generate a token under **Profile → API tokens** in
Dockhand, and paste it in.

No-auth installations are unaffected.

### Changed

- Token authentication via `Authorization: Bearer dh_...` replaces session
  cookies. Tokens do not expire, eliminating periodic re-auth prompts.
- Setup flow probes the server first; a token is only requested on 401.
- Stack start/stop/restart actions now send `Accept: application/json`,
  causing Dockhand to execute synchronously and return real results.
- Minimum Python version raised to 3.14 (matching HA 2026.3).

## [1.1.0] — 2026-03-19

### Added

- No-auth support for Dockhand instances with authentication disabled. The
  setup flow probes the server first and skips credentials if no 401 is
  returned.

### Fixed

- Setup called `async_login()` even for no-auth installs, causing 400 errors.
- MFA token submission failed after the config flow rewrite.

## [1.0.1] — 2026-03-19

### Fixed

- Stack devices pre-registered with bare name instead of environment-prefixed
  name, causing entity ID collisions across environments.
- Stale cleanup listeners registered after platform setup, allowing old and
  new devices to briefly coexist and trigger `_2` suffixes.
- Stale image, network, and volume entities not cleaned up until the next slow
  poll; cleanup now runs immediately on setup.
- `icons.json` entries never applied due to missing `entity` section in
  `strings.json` and missing `_attr_translation_key` on entities.

## [1.0.0] — 2026-03-08

Initial stable release.

[Unreleased]: https://github.com/raetha/ha-dockhand/compare/v1.7.4...HEAD
[1.7.4]: https://github.com/raetha/ha-dockhand/compare/v1.7.3...v1.7.4
[1.7.3]: https://github.com/raetha/ha-dockhand/compare/v1.7.2...v1.7.3
[1.7.2]: https://github.com/raetha/ha-dockhand/compare/v1.7.1...v1.7.2
[1.7.1]: https://github.com/raetha/ha-dockhand/compare/v1.7.0...v1.7.1
[1.7.0]: https://github.com/raetha/ha-dockhand/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/raetha/ha-dockhand/compare/v1.5.1...v1.6.0
[1.5.1]: https://github.com/raetha/ha-dockhand/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/raetha/ha-dockhand/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/raetha/ha-dockhand/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/raetha/ha-dockhand/compare/v1.3.1...v1.4.0
[1.3.1]: https://github.com/raetha/ha-dockhand/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/raetha/ha-dockhand/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/raetha/ha-dockhand/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/raetha/ha-dockhand/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/raetha/ha-dockhand/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/raetha/ha-dockhand/releases/tag/v1.0.0
