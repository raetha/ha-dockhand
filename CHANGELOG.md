# Changelog

## [1.9.2] — 2026-09-01

### Fixed

- **Transient Dockhand 401 responses no longer immediately trigger a re-authentication
  prompt** (issue #18). Previously, a single 401 on the fast coordinator's first API
  call would surface `ConfigEntryAuthFailed` right away — prompting the user to
  re-enter credentials that hadn't actually changed. The integration now retries up to
  twice (waiting 5 s then 25 s) before concluding the token is genuinely invalid and
  surfacing the re-auth dialog. If the token recovers — as it reliably does when the
  cause is a brief Dockhand restart or Hawser connectivity hiccup rather than a
  revoked token — the failure is logged and the poll continues normally without
  disturbing the user. If all three attempts return 401, re-auth is surfaced as before.
  Non-auth failures (network errors, 5xx, etc.) still propagate immediately and are
  unaffected by this change.

- **The specific endpoint and response body are now logged when a 401 is received**,
  making future occurrences easier to diagnose — the log now shows which API call
  returned 401 and what Dockhand said in the response body, rather than only "token
  invalid or revoked."

## [1.9.1] — 2026-08-31

**ha-dockhand-cards users:** the device identifier format change below requires
ha-dockhand-cards 1.2.1 or later. Install it before (or immediately after)
upgrading ha-dockhand to restore card functionality.

### Fixed

- **Device identifier collisions when two Dockhand instances are configured in the same
  Home Assistant installation** (issue #28). Each Dockhand config entry now scopes its
  device identifiers with its own `entry_id` prefix (e.g. `env_1` becomes
  `abc12345-..._env_1`), so two entries that each manage an environment numbered `1`
  no longer merge into the same device in HA's device registry. This pattern matches
  how unique entity IDs have been scoped since v1.7.3 — the device identifier side was
  simply missed at the time.

  A one-time migration runs automatically on upgrade: every device belonging to this
  config entry that still has the old bare identifier is renamed to the new
  `{entry_id}_…` form. No action needed; existing devices and their entity_ids are
  unchanged — only the internal registry key updates.

  The migration runs before device pre-registration in the setup sequence, so
  the registry is already in the correct state by the time `async_get_or_create`
  is called — no `DeviceIdentifierCollisionError` on first boot after upgrade.

## [1.9.0] — 2026-07-30

### Added

- **Environment-scoped Schedules devices.** Schedules tied to a specific environment
  (container auto-update, git stack sync, environment update check, image prune,
  backup) now group under that environment's own "Schedules" device, the same way
  Stacks/Images/Networks/Volumes already do — instead of every schedule sitting flat
  under the single "Dockhand – Schedules" hub regardless of which environment it
  belongs to. Each env-scoped schedule device's name is prefixed with that
  environment's own name too (e.g. "Aurora – Schedules – nightly-backup"), not
  "Dockhand". Genuinely global schedules (system cleanup jobs, and any
  destination-level maintenance jobs Dockhand may expose) still live under the hub,
  keeping the "Dockhand" prefix, since they have no environment to group under. No
  action needed — existing schedule entities keep their same `entity_id`; only where
  they show up in the device list (and their device's display name) changes, and it
  corrects itself automatically on the next reload.
- The "Next run" schedule sensor now also exposes `name`, `description`, and
  `is_system` attributes, sourced directly from Dockhand's own schedule data.
- **A Home Assistant Repair issue (Settings → System → Repairs) now appears whenever
  Dockhand can't fetch part of its data** — one for schedules/environments-level
  failures, one per affected environment listing whichever of its own resources
  (images, networks, volumes, runtime controls, vulnerabilities, etc.) are currently
  failing to fetch. Previously the only trace of this was a warning logged and easy to
  miss; existing devices and entities are always left untouched while this is
  happening (see the Fixed section below), but there was no obvious place to actually
  go check *why* something looked stale or unavailable. Clears itself automatically
  the moment a fetch succeeds again — nothing to dismiss or clean up by hand.

### Changed

- **The "Last status" schedule sensor is no longer a diagnostic entity.** It now
  shows in the main section of a schedule device rather than tucked under
  "Diagnostic," matching how every other "current status" sensor in this
  integration is treated (stack status, git stack sync status). It's also now the
  more complete of the two schedule sensors: alongside its existing execution
  details, it carries `name`, `description`, `is_system`, `cron_expression`,
  `enabled`, `environment`, and `schedule_type` — the last four duplicated from
  "Next run" (which keeps them too, unchanged) rather than moved, so nothing
  already depending on them there is affected.

### Fixed

- **A transient API failure fetching containers, stacks, schedules, images, networks,
  volumes, or git stacks could silently look identical to "this is genuinely empty
  now," causing the corresponding entities and devices to be wrongly removed as
  confirmed-deleted.** Reported directly: schedule entities disappearing with no
  clear cause, suspected to follow a DNS resolution failure or similar transient
  network issue. Root cause: several per-resource fetches were gathered with
  `return_exceptions=True` and any failure silently defaulted to an empty
  list/dict, with the overall poll still reporting success — meaning cleanup logic
  had no way to distinguish "the fetch actually failed" from "there's really
  nothing here anymore." Fixed by tracking which specific resource failed to
  fetch each cycle (not just whether the poll as a whole succeeded), and having
  cleanup logic check that signal before trusting an empty result as grounds for
  removal — for containers, stacks, schedules, images, networks, volumes, and git
  stacks (every
  resource whose data determines entity/device existence via cleanup, not just
  displayed values on already-existing entities). See `docs/ARCHITECTURE.md` §9.
- **A device removed by cleanup — correctly or incorrectly — could permanently
  lose its entities, surviving even a restart.** The device itself would come
  back correctly (device creation is idempotent), but entity creation was gated
  by an in-memory "have I already added this" cache that was never cleared when
  something removed the entity out from under it — so once an ID was ever marked
  "known," nothing ever tried to recreate it again. Fixed by scoping that cache
  to the current session (`entry.runtime_data`, reset fresh on every reload or
  restart) rather than letting it persist indefinitely, and by having it
  double-check a cache hit is still actually present before trusting it — a
  device/entity removed during a session reappears correctly the next time its
  data is confirmed genuinely back, without needing a reload or restart at all.
  Affects every dynamically-created entity type (containers, stacks, images,
  networks, volumes, schedules, git stacks, update entities, and the
  per-environment sensors) — same underlying mechanism, all fixed together. Also
  fixed one related latent gap this surfaced: turning on "Enable container
  stats" for a container that already existed before that point would never
  create its stats sensors until a restart, since they were incorrectly nested
  inside the container's own already-registered check rather than tracked
  independently. If you were already missing entities because of the bug above
  before upgrading, reloading the integration (or restarting Home Assistant)
  after upgrading will bring them back.
- **The Stacks group device (the "Stacks" device an environment's individual
  stack devices live under) had no cleanup path at all** — unlike every other
  group device (Containers/Images/Networks/Volumes/Schedules), which all do. Not
  related to the fetch-failure or entity-recreation bugs above — the opposite
  problem, actually: an empty, no-longer-needed group device just never got
  removed once an environment's last stack was genuinely deleted. Fixed the same
  way as the Containers group device it was always meant to mirror.
- **Disabling "Enable schedules" could leave individual schedule devices behind
  permanently**, un-parented from the hub that had just been removed, instead of
  being cleaned up. Existing installs will see these disappear automatically on the
  next reload after upgrading, if any were left over from before.
- **The Images/Networks/Volumes group devices had no cleanup path at all** — toggling
  the corresponding option off correctly removed the individual entities but left an
  empty, useless group device behind indefinitely. These are now removed correctly,
  whether the option is off or the resource list is simply confirmed empty.
- **A swallowed fetch failure for `runtime_config`, `vulnerabilities`, `host`,
  `auto_update_settings`, or `recent_events` used to show a stale or misleadingly
  empty value with no indication anything was wrong** — e.g. a vulnerability count
  reading 0 when the real answer was unknown, or a container's memory limit number
  showing its last-known value (or nothing at all) indefinitely if that one fetch kept
  failing. These five don't determine entity/device *existence* the way schedules/
  images/networks/volumes/git stacks do (nothing gets deleted), so this is the
  companion fix for the other half of the same root cause: the runtime-control
  number/select entities, the vulnerabilities and Hawser-agent-version sensors, and
  the container auto-update switch now correctly report unavailable instead of a
  possibly-wrong value while their specific data can't be fetched — and the
  environment activity sensor's `recent_events` attribute reports unknown rather than
  an empty list, without affecting the sensor's own (unaffected, fast-data-derived)
  state. See `docs/ARCHITECTURE.md` §9.

### Internal

- **A container/stack lookup-by-name helper was duplicated across seven and four
  platform files respectively** (`_container()`/`_stack()` in `sensor.py`,
  `binary_sensor.py`, `button.py`, `number.py`, `select.py`, `switch.py`,
  `update.py`) — one copy (`update.py`'s) had already drifted to bypass the
  existing `_coordinator_env()` helper and reimplement its equivalent manually,
  functionally identical but a real example of exactly the kind of silent
  divergence that let the entity-recreation bug above go unnoticed in one file
  while already fixed in the others. Consolidated into `helpers.py`'s new
  `_find_container()`/`_find_stack()`, same move this file's own `_coordinator_env()`
  already made once before for the same reason. See `CONTRIBUTING.md`'s Code
  style section for the resulting guideline.

## [1.8.2] — 2026-07-28

### Fixed

- **The "containers" sensor's pending-updates reporting is now split into three attributes**:
  `pending_updates` (containers eligible for a bulk update — excludes system containers, which
  Dockhand's own bulk-update action was never meant to touch), `pending_system_updates` (system
  containers only), and `pending_updates_total` (both combined). Previously a single
  `pending_updates` attribute undercounted real pending updates on system containers, matching a
  quirk of Dockhand's own dashboard tile. **If you have an automation or template using
  `pending_updates` to mean "any container needs an update," switch it to `pending_updates_total`**
  — `pending_updates` now specifically means "eligible for the bulk-update button."
- **A configured API URL with incidental leading/trailing whitespace** (e.g. from copy-pasting)
  could produce a malformed link, silently breaking every "open in Dockhand" link the companion
  cards set. Existing configurations are corrected automatically — no need to re-enter anything.
- Identifiers used in Dockhand API requests are now properly encoded, fixing a rare bug for
  stacks/containers with spaces or other special characters in their names, and adding defense in
  depth against a maliciously crafted identifier from a compromised Dockhand instance.

## [1.8.1] — 2026-07-24

### Added

- **New "Enable update entities" option** (Settings → Configure, on by default). Turn it off if
  you manage container updates another way and don't want Dockhand's containers showing up in
  Home Assistant's own update management. The "Update all" button disappears when this is off;
  "Check for updates" and "Enable precise update versions" keep working regardless, since
  checking for updates on its own doesn't change anything.
  ([#23](https://github.com/raetha/ha-dockhand/issues/23))
- The "Check for updates" button now always appears on every environment device and no longer
  needs "Enable precise update versions" turned on to work. Pressing it forces an immediate
  check against Dockhand and updates whatever's enabled locally right away, instead of waiting
  for the next scheduled poll.

### Fixed

- Update entities could keep showing "update available" for up to 24 hours after the update had
  already been applied, when "Enable precise update versions" is on. The "Update all" button
  could also disagree with what the individual update entities showed, for the same reason.
- The very first setup screen (shown once, when adding the integration) had been out of date
  since before 1.8.0 — missing a couple of options that the later Configure screen already had.

## [1.8.0] — 2026-07-21

### Added

- **New "Enable container stats" option** (Settings → Configure) — creates the per-container
  CPU, memory, network, and block I/O sensors, instead of not creating them at all until you turn
  it on. Off by default since it's a lot of entities most people don't need. Genuinely gates the
  underlying stats API call too, not just entity creation — when off, that call isn't made at all
  (previously it ran unconditionally regardless of the option; fixed to actually skip it, since
  nothing consumes the result when it's off). A container that's stopped, or drops out of the
  stats response for any other reason, reports these sensors as unavailable rather than a stale
  or zero reading. Turning the option off now correctly removes any previously-created stats
  entities via the existing cleanup system, the same way enable_images/enable_volumes/
  enable_networks already do — they weren't being cleaned up before because they were always
  being created (just disabled-by-default) regardless of the option. If you'd already manually
  enabled any of these sensors on an earlier release, a one-time migration turns this option on
  automatically so you don't lose them.

- **CPU usage sensor now includes a `top_containers` attribute** (top 5 by CPU, with name/CPU%/
  memory%) when "Enable container stats" is on — same underlying data as the per-container
  sensors, just ranked and attached to one entity instead of needing all of them individually
  enabled. Lets a dashboard show "top containers by CPU" with one entity instead of many.

- **Stack status, container state, and container update entities now include a `name`
  attribute** — the raw Docker name (e.g. `traefik`), not the full device display name (e.g.
  "Forseti – Containers – Traefik") — for dashboards that want to show just the name. Stack
  status also gained a `type` attribute (`Internal`/`Git`/`Untracked`).

- **New companion repo: [ha-dockhand-cards](https://github.com/raetha/ha-dockhand-cards)** —
  Lovelace dashboard cards (environment, environment overview, vulnerability, stack, and
  container) built on top of this integration's entities. Separate HACS install (category:
  Dashboard/Plugin), since a card is a frontend resource, not part of this integration.

- **New "Connection type" sensor per environment** — socket / direct / Hawser (standard or
  edge), matching Dockhand's own connection-type indicator, with a matching icon per type.
  Enabled by default.

- **New consolidated "Disk usage" sensor per environment** (disabled by default), replacing the
  earlier separate "Containers disk usage" and "Build cache size" sensors — one sensor now
  covers images, volumes, containers, and build cache size together, matching Dockhand's own
  disk-usage breakdown. A one-time migration removes the two retired sensors' registry entries
  automatically, rather than leaving them to orphan.

- **Stack status and "Containers in stack" sensors now include a `container_names` attribute**
  (sorted alphabetically), and the "Updates available" sensor gained a `pending_container_names`
  attribute (also sorted) listing just the containers with a pending update — useful for a
  dashboard that wants the container list at a glance without navigating away.

- **New: "Redeploy" button on internal stacks** — pulls the latest image
  for each service and redeploys, recreating only what actually
  changed. Named and behaves exactly like Dockhand's own Redeploy
  popover, including its own literal button title. Not created for
  git-tracked or Untracked stacks (git stacks already have their own
  Deploy/Sync from Git button, with different mechanics — see the
  README for why they aren't identical) or for a stack containing a
  system container.

- **New: bulk "Update all" button per environment**, appearing only
  while at least one container has a pending update — matching
  Dockhand's own "Update all" button, including its name and the fact
  that it doesn't exist at all when there's nothing to update, not just
  disabled. Updates every pending container in one batch (with
  vulnerability scanning, same as individual updates) instead of one
  API call per container.

- **New: "Updates available" sensor on each stack**, showing whether any
  container in the stack has a pending image update, with an update
  count attribute. Requires Dockhand 1.0.37 or later — automatically
  skipped on older versions rather than requiring any configuration.

- **Update entities now appear automatically** for every container in an
  environment where update-check is enabled in Dockhand — no setup
  required. They show the current image tag, flip to "update-pending" as
  soon as Dockhand notices an update is available, and Install works
  right away.

  The old **Enable container updates** option is renamed **Enable
  precise update versions**. It's no longer required to get update
  entities at all — turning it on now just upgrades them to show exact
  image versions (digests) via periodic registry checks. Your existing
  setting is carried over automatically.

- **New git stack entities** for git-tracked stacks: sync status, last
  sync time, and sync error, plus a Deploy/Sync from Git button (its
  name and icon match Dockhand's own equivalent exactly, including
  switching between the two depending on whether the stack is currently
  running) and an Auto-deploy switch.

- **New container Auto-update switch** — toggle Dockhand's own scheduled
  auto-update check for a container directly from Home Assistant.

- **New runtime controls** (opt-in via **Enable runtime controls**) for
  containers not managed by a Compose stack: adjust memory limit, CPU
  limit, process limit, and restart policy without recreating the
  container. Includes an automatic safety check that reverts a
  memory-limit change and raises a repair issue if it causes the
  container to stop running.

- **Stack devices now show their type** (Internal, Git, or Untracked) so
  you can tell at a glance why a stack does or doesn't have the git sync
  entities above.

- **Activity events sensor now includes a `recent_events` attribute**
  (last 10 events, when activity collection is on for that environment)
  alongside the existing today/total counts — useful for dashboards that
  want to show a live feed without a separate integration.

- **Online sensor now includes a `labels` attribute** listing the tags
  you've assigned to the environment in Dockhand.

- **New "Vulnerabilities" sensor per environment** (disabled by default —
  enable it in **Settings → Entities**), showing the total finding count
  from Dockhand's own vulnerability scanner with a severity breakdown
  (critical/high/medium/low) and scan coverage as attributes. Only polled
  when vulnerability scanning is enabled for that environment.

- **New sensors, disabled by default** (enable what you want in
  **Settings → Entities**): host platform (with an `architecture`
  attribute), Docker version, and last boot time; an "Image pruning"
  sensor; and Hawser agent identity details as attributes on the Hawser
  version sensor (edge-mode connections only).

- **A few existing sensors gained useful attributes** instead of new
  entities: CPU count on CPU usage, and environment name/connection
  details on the Online sensor.

### Changed

- **The "Updates available" sensor on each stack no longer uses the "Problem" device class**,
  which made a routine available update look like something was wrong. It now shows as a plain
  on/off sensor instead.

- **Changing an option now takes effect immediately** (a reload happens automatically) instead of
  waiting for the next poll or requiring a manual reload of the integration.

- **"Update all" button no longer includes a live count in its name**
  (was "Update all (3)") — now a plain "Update all containers". A changing
  friendly_name on a persistent entity read as confusing churn; the count
  is still visible via the button's own state/attributes if needed.

- **"Host last boot" renamed to "Uptime"**, matching Dockhand's own API
  field name. Still a timestamp under the hood (boot time) — set the
  entity's own "Display as: Relative time" option in Home Assistant if you
  want it to read "2 days ago" rather than a fixed date/time; that's a
  native HA display option for any timestamp sensor, not something this
  integration needs to compute itself.

- **Environment sub-devices (Containers, Stacks, Networks, Images, Volumes)
  now show as model "Environment Group"** instead of "Environment" — makes
  it clear at a glance which device is the actual environment versus one of
  its groupings, in Home Assistant's own device list as well as when
  picking a device for a dashboard card.

- **The environment device's settings link now opens that specific
  environment's edit form** (`/settings?tab=environments&edit=<id>`) instead
  of the generic environments list — matches what Dockhand's own dashboard
  settings gear does.

- **Installing a container update now runs vulnerability scanning** (if
  configured on the environment) and **honors your configured blocking
  policy** — matching what Dockhand's own UI does. Install progress is
  also more accurate.

- **"Activity logging" renamed to "Activity collection"**, to match
  "Metrics collection".

- **The container/stack Start-Stop switch, Restart button, container
  Auto-update switch, and runtime controls (memory/CPU/process limits,
  restart policy) are no longer created for Dockhand's own
  infrastructure** (its management container, or a Hawser agent) — or,
  for the switch and button, for a stack containing one. This prevents
  accidentally restarting, updating, or reconfiguring the very thing
  that lets Home Assistant manage your containers in the first place.

- **Reduced how often the integration touches your Dockhand connection
  credentials** during normal polling, and added a second layer of
  redaction in diagnostics exports as a safety net.

- **Several entity icons now match Dockhand's own** (online status,
  image/volume counts, activity/metrics/scanning/update-check status) so
  they're easier to recognize across both UIs.

### Fixed

- **Several sensors could log an `AttributeError` and fail to update instead of just going
  unavailable**, when Dockhand's API sent certain optional fields as an explicit `null` rather
  than omitting them — most visibly CPU/memory usage sensors (both the per-container ones
  originally reported in #20, and an environment-level one found during this fix), but the same
  underlying gap affected roughly two dozen call sites across nearly every entity type. Fixes
  #20.

- **A total failure to reach Dockhand (e.g. DNS resolution failure to the configured hostname)
  no longer looks like every stack and container disappearing.** It was being caught and logged
  as a warning, then quietly treated as "zero environments right now" — which fed through every
  safety check that assumes present-but-empty coordinator data is trustworthy, and could trigger
  the cleanup system to remove devices for environments that were actually just temporarily
  unreachable. Now correctly fails the update instead: entities go unavailable, nothing gets
  cleaned up, and reloading the integration while the outage persists surfaces a real "not ready"
  failure instead of a misleading success.

- **Hawser agent version now reports correctly for standard-mode
  (port-bind) connections** — it previously always showed unavailable
  for this connection type.

- **Image sensors no longer pick up a stray "_2" in their entity ID after
  a container update.** When a container is updated, Docker briefly has
  two images claiming the same name — the new one just pulled, and the
  old one not yet cleaned up. Image sensors now wait for that to settle
  before creating a new entity, so the correct one gets the clean name
  instead of a manual "recreate entity IDs" being needed afterward.

- **Health sensor is now removed if a container loses its healthcheck**
  — if an image update dropped a container's `HEALTHCHECK` instruction,
  its Health sensor previously stuck around permanently showing stale
  data instead of being cleaned up.

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

## [1.7.2] — 2026-06-12

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

[Unreleased]: https://github.com/raetha/ha-dockhand/compare/v1.9.2...HEAD
[1.9.2]: https://github.com/raetha/ha-dockhand/compare/v1.9.1...v1.9.2
[1.9.1]: https://github.com/raetha/ha-dockhand/compare/v1.9.0...v1.9.1
[1.9.0]: https://github.com/raetha/ha-dockhand/compare/v1.8.2...v1.9.0
[1.8.2]: https://github.com/raetha/ha-dockhand/compare/v1.8.1...v1.8.2
[1.8.1]: https://github.com/raetha/ha-dockhand/compare/v1.8.0...v1.8.1
[1.8.0]: https://github.com/raetha/ha-dockhand/compare/v1.7.4...v1.8.0
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
