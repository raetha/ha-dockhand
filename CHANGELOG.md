# Changelog

## [Unreleased]

## [1.4.0] — 2026-05-06

### Added

- **Container update entities** — an optional `update` platform adds one
  [`UpdateEntity`](https://developers.home-assistant.io/docs/core/entity/update/)
  per container. Enable via **Configure → Enable container update entities**.
  - Update availability is checked on a configurable interval (default 24 h)
    by calling Dockhand's `POST /api/containers/check-updates`, which performs
    real registry queries — kept infrequent to avoid unnecessary load on the
    Docker host
  - Installed and latest versions are displayed as short digest hashes (first
    12 hex chars of the sha256)
  - **Install** triggers Dockhand's safe-pull workflow, including vulnerability
    scanning if configured in Dockhand
  - Install is suppressed for Dockhand system containers (e.g. `hawser`) and
    containers with the `dockhand.update=false` label
- **"Check for image updates" button** — each environment device gains a
  button to trigger an immediate update check on demand, without waiting for
  the next scheduled poll. Only visible when container update entities are
  enabled.

### Fixed

- Entity names now correctly use translated strings in all supported languages.
  A hardcoded English `_attr_name` was overriding the translation system on 26
  entity classes across sensors, binary sensors, switches, buttons, and the new
  update entity. Non-English users would have seen English entity names
  regardless of their HA language setting.

### Changed

- Dashboard stats are now fetched in a single `GET /api/dashboard/stats` call
  per poll cycle instead of one call per environment, reducing API calls
  proportionally to the number of connected environments.
- Registry cleanup (stale containers, stacks, environments, schedules, images,
  networks, volumes, and update entities) is now handled by a single unified
  function called from all coordinator listeners, replacing three separate
  functions with inconsistent guard logic. Environment hub devices, group
  devices, and schedule devices are now properly removed when permanently
  deleted from Dockhand (previously only containers and stacks were cleaned up).
- The update coordinator no longer makes a redundant `GET /api/environments`
  call on each poll — it reuses the fast coordinator's already-fetched
  environment list.

## [1.3.1] — 2026-05-03

### Changed

- **Storage sensors now use bytes as the native unit** — `Containers disk usage` and
  `Build cache size` previously divided the API byte values by 1,048,576 and stored
  the result as `MiB`. They now store the raw byte value returned by the API
  (`native_unit_of_measurement = B`) and declare `suggested_unit_of_measurement = MiB`
  so Home Assistant displays MiB by default while allowing users to change the display
  unit freely per-entity. This is consistent with how HA core handles data-size sensors
  and eliminates the precision loss from pre-converting to MiB.
  **Migration note:** automations or templates that compared the raw numeric state of
  these sensors against a MiB threshold (e.g. `> 500`) will need to be updated to use
  byte values (e.g. `> 524288000`) or switch to using the entity's display value.

### Fixed

- **CPU usage sensor reporting inflated values** — `cpuPercent` from the Dockhand API is
  already a true percentage (e.g. `23.5` for 23.5% CPU). The sensor was incorrectly
  multiplying it by 100, causing values up to 100× too high. The value is now passed
  through with only a `round()`, consistent with how `memoryPercent` has always been
  handled. Fixes [#7](https://github.com/raetha/ha-dockhand/issues/7).

## [1.3.0] — 2026-05-01

### Changes

**Localization**
- Added machine-generated translations for 10 languages: German (`de`), Spanish (`es`),
  French (`fr`), Italian (`it`), Norwegian Bokmål (`nb`), Dutch (`nl`), Polish (`pl`),
  Portuguese (`pt`), Swedish (`sv`), and Chinese Simplified (`zh-Hans`). All 91
  translatable strings are covered in each language
- Updated `CONTRIBUTING.md` with guidance for correcting existing translations and
  submitting new languages — no Python or test-suite knowledge required for
  translation-only PRs
- Added `## Translations` section to `README.md` summarising supported languages and
  linking to the contribution guide

## [1.2.0] — 2026-04-28


**Breaking change** — session-cookie authentication (username + password + MFA) has been
removed. The integration now authenticates exclusively via Dockhand API tokens or requires
no authentication at all (when Dockhand authentication is disabled).

Requires **Dockhand ≥ 1.0.26** for reliable token authentication.

### Migration

Existing installations using username/password will be flagged for re-authentication on
the next HA restart. Go to **Settings → Devices & Services → Dockhand → Re-authenticate**,
then generate an API token in Dockhand under **Profile → API tokens** and paste it in.

No-auth installations (Dockhand authentication disabled) are unaffected and require no
action.

### Changes

**Authentication**
- **Token authentication**: all API requests now use `Authorization: Bearer dh_...`
  instead of session cookies. Tokens do not expire on a 24-hour session timeout,
  eliminating the periodic re-authentication prompts that affected MFA users
- **Removed**: username, password, and MFA fields from the config flow. Setup now
  probes the server first; a token is only requested if the server returns 401
- **Removed**: `DockhandMFARequiredError`, `DockhandAuthError` login path, and all
  `async_login()` logic from the API client
- **Fixed**: legacy config entries (pre-1.2.0) that stored a session cookie alongside
  a newly provided API token no longer loop on startup — the legacy keys are stripped
  on first successful setup after re-authentication

**API**
- **Fixed**: stack start/stop/restart actions now send `Accept: application/json`,
  causing Dockhand to execute the operation synchronously and return a real result
  rather than a job-ID for async polling. Switch and button entities now correctly
  surface failures instead of silently succeeding

**Code quality**
- **Python 3.14**: minimum Python version raised to 3.14 (matching Home Assistant
  2026.3). `from __future__ import annotations` removed from all files — lazy
  annotation evaluation is now the default interpreter behaviour
- **Ruff format**: code is now fully formatted with `ruff format` in addition to
  passing `ruff check`. Both checks run in CI and in the local test runner
- **Ruff config**: lint configuration moved from inline CI flags to `.ruff.toml` at
  repo root, with a documented rule set and per-file ignores for tests
- **Dead code removed**: unreachable retry block after `_handle_reauth` in the fast
  coordinator collapsed; unused imports (`DockhandAuthError` in `__init__.py`,
  `DockhandError` in `config_flow.py`) removed

**Repository**
- Added `.github/ISSUE_TEMPLATE/` with bug report, feature request, and blank issue
  configuration templates
- Added `dependabot.yml` for automated weekly updates of GitHub Actions and pip
  dependencies
- Added `CONTRIBUTING.md` with development setup, test/lint instructions, and
  pre-PR checklist
- Added `.gitattributes` enforcing LF line endings across all platforms
- GitHub Actions bumped: `actions/checkout@v6`, `actions/setup-python@v6`
- `manifest.json` now declares `"homeassistant": "2026.3.0"` minimum version

**Fixes**
- Removed invalid `homeassistant` key from `manifest.json` — hassfest rejects
  this key in custom integrations; minimum HA version is correctly expressed
  in `hacs.json` only
- Fixed `asyncio.get_event_loop()` usage in all test files — Python 3.14 no
  longer implicitly creates an event loop in the main thread; replaced with
  `asyncio.run` throughout
- Fixed `ha_stubs.py` Python 2-style `except ValueError, AttributeError:` to
  parenthesised form `except (ValueError, AttributeError):`
- Bumped `actions/stale@v9 → v10` and `softprops/action-gh-release@v2 → v3`
  (Dependabot)
- Cleaned up unused local variables in test files (`sc`, `hub`, `devs`,
  `fast`, `slow`) and tightened `.ruff.toml` test suppressions to properly
  accommodate the `locals()`-based lazy-import pattern and bootstrap ordering
  constraints

## [1.1.0] — 2026-03-19

Adds support for Dockhand instances running without authentication, and redesigns the config flow to auto-detect whether credentials are needed.

### New features
- **No-auth support**: the integration now works when Dockhand authentication is fully disabled. The setup flow probes the server first — if it responds without a 401, credentials are skipped entirely and no username or password is stored
- **Auto-detecting config flow**: setup and reconfigure no longer show a username/password screen by default. Credentials are only requested if the server returns a 401, mirroring how the MFA screen already worked. The `auth_enabled` checkbox from the previous approach has been removed entirely

### Behaviour changes
- Reconfigure now detects auth state from the server: if Dockhand authentication was disabled since the last setup, stored credentials are automatically removed on reconfigure
- If a no-auth install receives a 401 (e.g. authentication was re-enabled in Dockhand), the integration surfaces a clear reconfigure prompt rather than silently failing

### Bug fixes
- Fixed: `async_setup_entry` called `async_login()` even for no-auth installs (no username stored), causing HTTP 400 `Authentication is not enabled` errors on startup
- Fixed: MFA token submission failed after the config flow rewrite because credentials were not preserved in `_connection_data` before redirecting to the MFA step

## [1.0.1] — 2026-03-19

Patch release fixing entity ID suffix accumulation, stale entity cleanup, and icons.

### Bug fixes
- Fixed: stack devices pre-registered with bare name instead of environment-prefixed name (e.g. `traefik` instead of `Heimdall – traefik`), causing entity IDs for compose-managed containers to be generated without the environment prefix and colliding across environments
- Fixed: stale cleanup listeners were registered after platform setup, so cleanup fired after `async_add_entities` rather than before — allowing old and new container/image devices to briefly coexist and trigger `_2` suffixes on entity IDs
- Fixed: stale image, network, and volume entities were not cleaned up until the next slow coordinator poll (up to 600 s after reload); cleanup now runs immediately on integration setup so pruned resources are removed before new entities are registered
- Fixed: `icons.json` entries were never applied because no entity had `_attr_translation_key` set and `strings.json` lacked the required `entity` section; all 22 statically-named entities now declare their translation key
- Fixed: image and network sensors were missing `_attr_icon`; all three dynamic-name sensor types (image, network, volume) now have correct fallback icons

### Documentation
- README: added session timeout guidance — Dockhand defaults to 24 h; instructions to extend via Settings → Authentication → General → Session timeout
- README: added troubleshooting entry for `_2`/`_3` entity ID suffixes and how to resolve with Recreate entity IDs after a prune cycle

## [1.0.0] — 2026-03-08

Initial stable release of the Dockhand integration for Home Assistant.

### Architecture
- Dual-coordinator polling: fast (default 60 s) for containers, stacks, and environment stats; slow (default 600 s) for images, volumes, networks, and schedules
- Grouped device hierarchy per environment: `<Env> – Containers`, `<Env> – Stacks`, `<Env> – Networks`, `<Env> – Images`, `<Env> – Volumes`
- All resource devices prefixed with environment name (e.g. `Heimdall – traefik`) to disambiguate across environments
- `model` field on every device for type display in the HA device list
- Deep links from every device to its corresponding page in the Dockhand UI
- Stale device cleanup on coordinator refresh

### Authentication
- Local Dockhand user authentication with session-cookie persistence
- Full MFA (TOTP) support during setup, reconfigure, and re-authentication
- Options and Reconfigure flows to change poll intervals, feature flags, URL, or credentials without reinstalling

### Entities
- **Environment:** Online (binary_sensor), CPU usage, Memory usage, Containers running
- **Container:** State sensor, Health sensor (omitted if no healthcheck), Running switch (start/stop), Restart button
- **Stack:** Status sensor, Running switch (start/stop), Restart button
- **Network:** Connected container count with driver, scope, subnet, and container list attributes (optional)
- **Volume:** Connected container count with driver, mountpoint, and size attributes (optional)
- **Image:** Repository name with tag as state, size and container usage as attributes (optional)
- **Schedule:** Next run timestamp, Last status with error detail (optional, read-only)

### Quality
- 211 unit tests covering API client, config flow, coordinators, entities, and setup/teardown
- Passes hassfest and HACS validation
- Ruff lint clean

[Unreleased]: https://github.com/raetha/ha-dockhand/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/raetha/ha-dockhand/compare/v1.3.1...v1.4.0
[1.3.1]: https://github.com/raetha/ha-dockhand/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/raetha/ha-dockhand/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/raetha/ha-dockhand/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/raetha/ha-dockhand/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/raetha/ha-dockhand/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/raetha/ha-dockhand/releases/tag/v1.0.0
