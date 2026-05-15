# Changelog

## [Unreleased]

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

[Unreleased]: https://github.com/raetha/ha-dockhand/compare/v1.5.0...HEAD
[1.5.0]: https://github.com/raetha/ha-dockhand/compare/v1.4.1...v1.5.0
[1.4.1]: https://github.com/raetha/ha-dockhand/compare/v1.4.0...v1.4.1
[1.4.0]: https://github.com/raetha/ha-dockhand/compare/v1.3.1...v1.4.0
[1.3.1]: https://github.com/raetha/ha-dockhand/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/raetha/ha-dockhand/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/raetha/ha-dockhand/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/raetha/ha-dockhand/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/raetha/ha-dockhand/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/raetha/ha-dockhand/releases/tag/v1.0.0
