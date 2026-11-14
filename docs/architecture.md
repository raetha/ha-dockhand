# Architecture reference

Check this **before** adding an entity, device or config option. The conventions here aren't visible from any one platform file, and getting them wrong fails silently: entities that never clean up, or IDs that collide. Section numbers are referenced from code comments; keep them.

## 0. Device registration: two call sites, one set of factories

`DeviceInfo` reaches the device registry from two places that run at different times:

1. **An entity's `device_info`**, read only when that entity is first added.
2. **`_ensure_env_devices()` / `_ensure_hub_devices()`** (`helpers.py`), which call `registry.async_get_or_create()` on every coordinator update, so devices and their `via_device` parents exist before any entity needs them.

The registry overwrites `manufacturer`/`model`/`name` on every `async_get_or_create()`, so if the two computed a field differently, whichever ran last would win, silently, and the device would flip between values. Both therefore build every device from the same factory in `helpers.py`: `_env_device()`, `_container_device()`, `_stack_device()`, `_containers_group_device()`, `_stacks_group_device()`, `_network_group_device()`, `_image_group_device()`, `_volume_group_device()`, `_schedule_group_device()`, `_sched_device()`. The `_ensure_*` functions call them as `registry.async_get_or_create(config_entry_id=..., **factory(...))`.

- **A new device type or computed field:** add or extend the factory, call it from both sites, never write `DeviceInfo` fields inline. Test `_ensure_env_devices()` called repeatedly with the same input: a field that drifts only shows on the second call.
- **The instance device** (`{entry_id}_instance`) is the Dockhand server. It's registered in `async_setup_entry` before anything else, and `async_remove_config_entry_device` refuses it, so environments and the Schedules hub can be parented to it by `via_device_id` (HA 2026.10 deprecates `via_device` in `DeviceInfo`; `via_device_id` needs the registry id, hence the lookup). Only registration sets that parent; entity `device_info` omits it. It's named "Dockhand (*host*)" (`instance_host()`, the host the cards label an instance with), not after the entry, whose title is the API URL. Its entities' unique IDs are `{entry_id}_instance_{what}`: no env_id, so the cleanup's type dispatch skips them.
- **The instance update entity** is added only once Dockhand's own check (`/api/self-update/check`, in the version coordinator) answers without an `error`; Dockhand reports one when it can't inspect its own container, as when it reaches its hosts only through Hawser. A listener adds it when a later check works; once it's in the registry it's added on every setup, unavailable while the check can't tell.

## 1. Unique ID conventions

**Entity unique IDs:** `{entry_id}_{env_id}_{type}_{discriminator}`.

- `type` is one existing category word: `container`, `stack`, `image`, `network`, `volume`, `update`. Never a compound word (`git_stack`): cleanup reads `unique_id.split("_")[2]` as the type, and a compound word splits across two positions. An entity scoped to a container or stack uses that word, with everything distinguishing it in the discriminator (`stack_{name}_git_sync_status`).
- **Schedules are the exception:** `{entry_id}_sched_{id}_{type}_…`, because a schedule can be global (`environmentId: null`; system cleanup and destination-scoped repository jobs have no environment). Position 2 is then the schedule id, which matches no cleanup branch, so schedule entities rely on device-cascade removal. Which environment a schedule belongs to is expressed by `via_device` (`_sched_device()`, `_schedule_group_device()`), not by its IDs. Renaming them to the convention would change entity IDs for no gain.
- **Device identifiers:** `{DOMAIN}, "{type}_{env_id}_{name}"`: `env_{env_id}`, `container_{env_id}_{name}`, `stack_{env_id}_{name}`. Always from the factories; the cards match these patterns exactly. An entity on a container's or stack's device subclasses `entity.py`'s `DockhandContainerEntity`/`DockhandStackEntity`, which carry the identity, the data lookup and `device_info`.
- **Container and stack identity is name-based.** Container IDs change on every recreation (an image update, a redeploy); names are stable and unique per host. Stacks use the Compose project name. A git stack's `stackName` is always its Compose project name (`deployGitStack` runs `docker compose -p {stackName}`), which is why git stack entities share the stack's device.
- **New entity type:** copy the unique ID pattern of its closest existing analog.
- **`translation_key` is a contract with ha-dockhand-cards**, which finds entities by `platform: "dockhand"` + `translation_key` on a device, precisely because unique IDs are internal. Renaming one breaks the cards (and users' automations): treat it as a documented, migrated change. Adding one is free; the cards treat a missing key as "not on this version yet".

## 2. Entity cleanup

Cleanup is central, in `__init__.py`: `_build_live_sets()` computes what exists from all coordinators, and `_cleanup_stale_registry()` removes what doesn't, after every setup. Never build per-platform removal.

Recreating an entity cleanup removed is each platform's job: every platform checks `helpers.already_registered()` against `entry.runtime_data.known_entity_ids`, a set made fresh on every setup (§9).

What cleanup can't confirm is gone (an offline environment, a failed fetch) it keeps. For those, `async_remove_config_entry_device` lets the user delete a device from its page, refusing anything `_build_live_sets` still reports.

**Two passes:**

1. **Device registry:** removes `env_`/`container_`/`stack_` devices when their environment is deleted, or when it's online and a successful poll confirms the container or stack is gone. HA removes a device's entities with it.
2. **Entity registry:** entities with no device of their own (images, networks and volumes live on a group device), and entities whose existence depends on something other than their device (update entities on **Enable update entities**, runtime controls on their option and the container being stack-less, git stack entities on Dockhand still tracking the stack by git).

**The safety rule, for every category:**

- Remove when the environment no longer exists.
- Remove when the environment is online and a successful poll confirms the item or condition is gone.
- **Never** remove on a failed poll or while the environment is offline. A stale entity is a much smaller problem than deleting one that's real but unreachable.

**Adding a conditionally present entity type:**

1. If its existence can change while its device persists, it needs entity-registry tracking: device cascade won't remove it.
2. In `_build_live_sets`, add a live-UID set from the coordinator that decides its existence (fast for anything from containers, stacks or dashboard stats; slow for images, volumes, networks, git stacks or runtime config, guarded by `slow_valid`).
3. Add the matching branch in `_cleanup_stale_registry`, following the safety rule.
4. Test it in `test_init.py` like the runtime-control, git-stack and update tests: kept while live, removed when the condition flips, kept while offline or after a failed poll.

A missing cleanup case raises nothing and fails no test you didn't write, so check every new entity type against this section in review.

**Type-word collisions.** The entity pass dispatches on the word at position 2 alone. An always-present entity whose suffix merely *starts* with a type word (`update_check_enabled`, `image_prune_enabled`) would be checked against that type's live set, never found, and removed on every online poll. List such exact suffixes in `_TYPE_COLLISION_EXCLUDED_SUFFIXES`, or choose a suffix that doesn't start with one.

**Shared suffixes across categories.** Container stats sensors and runtime-control numbers both have `uid_type == "container"` and the suffix `memory_limit`, and each needs its own conditional tracking (`enable_resource_stats` vs runtime controls). They're told apart by entity domain (`sensor` vs `number`), checked before the suffix match. Don't add such a suffix to the exclusion list (that exempts it from cleanup), and don't rely on branch order alone: give them distinct domains or suffixes.

**Group devices need their own cleanup.** Removing a device removes its entities but not devices parented to it by `via_device` (HA clears their `via_device_id`). So every layer (the Schedules hub, each environment's Schedules group, each schedule device; the Containers, Stacks, Images, Networks and Volumes groups) has its own checks:

- **Feature disabled** (where the group has an option): checked unconditionally, not folded into a poll-gated flag that a transient failure could turn off.
- **Confirmed empty while enabled:** gated on `slow_valid`, `online_env_ids` and the resource's fetch-ok set, like everything else here. Containers and Stacks groups have no option, so only this case.

Removing a whole group removes its image, network or volume entities at once (the entity registry handles device removal synchronously), so the per-item entity branches are redundant then, but they're still the only thing that catches one item disappearing from a group that stays. Keep both; `entity_registry.async_remove()` ignores an already-removed entity.

## 3. Coordinators

- **`DockhandFastCoordinator` (60 s):** dashboard stats, containers, stacks, container and stack resource stats, pending-update flags. The only source of which environments exist.
- **`DockhandSlowCoordinator` (600 s):** images, volumes, networks, schedules, runtime controls, git stacks, host info, auto-update and environment settings, and `env_meta`. Two per-environment fetches are gated on Dockhand's own settings from the dashboard stats, so an environment not using the feature never pays for the call: `recent_events` (`/api/activity`, when `collectActivity` is on) and vulnerability counts (`/api/vulnerabilities/count`, when `scannerEnabled` is on). Its environment list comes from the fast coordinator, which finishes its first refresh first.
- **`DockhandUpdateCoordinator` (24 h, optional):** precise versions, only with **Enable precise updates**. Purely additive (below).
- **`DockhandVersionCoordinator` (6 h):** Dockhand's version from its bundled changelog (`GET /api/changelog`, public, newest first, about 100 KB), which changes only when Dockhand is upgraded. It feeds the instance device's `sw_version` (written by a listener, which also keeps it polling), diagnostics and the instance update entity. A failure is never fatal; the device keeps its last version.

**Fail, don't fake empty.** A coordinator's fetch returns what it knows is true or raises `UpdateFailed`; never an empty-but-successful result. An empty success reads downstream as "there are no environments", and cleanup acts on it (a DNS failure once made every stack and container look deleted). Raising keeps the last data, marks entities unavailable, and turns a failure during setup into `ConfigEntryNotReady`. The same holds per environment: the update coordinator keeps an environment's previous data when its check fails, rather than reporting no updates there. Partial failures within a successful poll: §9.

**`/api/environments` is never used to list environments, and its response is never stored:** it returns Dockhand's secrets (`tlsKey`, `hawserToken`) decrypted. Environments come from `/api/dashboard/stats`. The config flow calls it once as a connectivity probe (result discarded), and the slow coordinator reads from it only the fields nothing else has: image-prune enabled, Hawser agent name, id and last seen, and the connection's host and port, extracted into `env_meta` on receipt. A new field from it goes into that extraction, never the raw response.

**Two-tier update entities** (the template for "cheap signal + optional precision"): `ContainerUpdateEntity`'s coordinator is the fast one. Tier 1 (existence, the image tag as installed version, Dockhand's pending-update flag) works alone. Tier 2, when enabled, only upgrades installed and latest versions to precise digests on the same entities; it never decides whether an entity exists.

- **Enable update entities** (default on, for users who manage updates outside HA, issue #23) removes both tiers' entities and the **Update all** button, which would otherwise still trigger updates. It doesn't gate Tier 1's pending-update fetch (other entities use it), the update coordinator, or **Check for updates**: that button always runs Dockhand's check for its environment, and merges the result into Tier 2 (`async_merge_check_results()`) if it exists and into Tier 1 (`async_merge_pending_updates_from_check()`) if update entities are on. So pending-update data can exist with the platform off: anything about to *act* on it checks the option explicitly.
- **Update all** folds both tiers (`_container_has_pending_update()`) to decide whether it exists; safe because Tier 2 is looked up by current container id.
- **"Has an update" and "may be bulk-updated" are separate functions.** `_container_has_pending_update()` says nothing about system containers (Dockhand itself, Hawser agents), which must never be bulk-updated. Anything that acts calls `_actionable_pending_update_container_ids()`, built on `_container_is_bulk_update_eligible()`: both buttons and the Installable updates sensor do (`_pending_update_counts`). A safety exclusion gets its own named function, so using the unfiltered primitive to act stands out in review.
- **Look Tier 2 up by current container id, never by name.** A container recreated since the last 24 h check has a new id but the same name; looking up by id makes the stale entry simply not found.
- **System containers:** Dockhand's pending-updates table never holds them (its scheduled check and `check-updates` both skip them, though the response still reports `hasUpdate`), so `DockhandFastCoordinator` keeps those rows from check responses in `_system_check_results` and re-applies them after every pending-updates poll, pruned by current id. Dockhand computes `newerVersion` only for non-system containers (Finsys/dockhand#1466), so a pinned Dockhand or Hawser tag never shows an update there. For Dockhand itself, the update coordinator asks `/api/self-update/check` (a version tag compared with Dockhand's newest release): a newer one becomes the Dockhand row's `newerVersion` with `"source": "self-update"`, never overriding one check-updates reported. Its digest answer is ignored. It's called only when Dockhand's container is in a socket, direct or untyped environment (`_dockhand_host_candidates`, like Dockhand's `resolveOwnEnvId`), since through Hawser it always fails; every failure is silent. Hawser has no equivalent.

**Actions refresh what they changed, and await it.** Never `async_request_refresh()` after an explicit action: its debouncer can return at once and refresh 10 s later, so a card's progress or a script's next step would run before anything changed. Container and stack actions await `async_refresh_environment(env_id)`: a full poll's per-environment fetches (containers, stacks, update flags, resource stats) for that environment, keeping its dashboard stats. It doesn't reset the poll schedule (`async_set_updated_data()` would, so a busy environment could postpone the full poll forever), and a full poll finishing meanwhile wins. Per environment there's at most one refresh running and one queued; callers arriving during a run join the queued one, which starts after they all arrived, so each sees its own change (HA runs a service call's entities concurrently: `switch.turn_off` on ten containers costs two refreshes). The queued task uses `eager_start=False`, or it could start fetching before being registered and a later caller would join a fetch older than its action. Actions spanning environments, and the slow coordinator's, await `async_refresh()`. Exception: environment settings stored in Dockhand's dashboard stats request a fast refresh (§11).

**The live feed (`events.py`) is a latency shortcut, never a data source.** An `activity` event schedules `async_refresh_environment()` for its environment, debounced 2 s (Docker sends bursts: kill, die, stop), and skipped when the environment's data already comes from a fetch that started after the event (`fetched_since()`). `env_status` requests a full fast refresh, since online state comes from the dashboard stats. Nothing is patched from event payloads, so polled and refreshed data can't disagree.

- The feed opens only while some environment can send events (`collectActivity`, `collectMetrics`, or Hawser Edge; Dockhand's event worker skips the rest), re-checked on every fast poll, and only after HA has started.
- After a reconnect (not the first connect) the fast and version coordinators refresh, covering missed events and a Dockhand upgrade.
- A 30 s read timeout against Dockhand's 5 s heartbeat detects a dead connection. Retries back off 5 s → 5 min, reset only once a heartbeat arrives (with no environments the stream is silent); 403/404 (no `activity: view`, or an older Dockhand) retry hourly.
- `iot_class` stays `local_polling`: polling is the source of truth.

**Installs share Dockhand jobs (`installs.py`).** `DockhandInstaller`, one per entry, owns every install: an update entity's Install and **Update all** both call `async_install(env_id, ids)`.

- The first call for an environment creates a batch and a task that waits `GATHER_SECONDS` (2 s), then takes the environment's lock. Calls until then join that batch, later ones a new one, because `batch-update-stream` fixes its container list when it starts. The task uses `eager_start=False`, as above. One job runs per environment at a time.
- Outcomes per container come from the job's lines, first verdict wins: blocked, failed, skipped, or done. Dockhand reports every container it handles, so one it never mentions wasn't updated. A job-level failure is every container's outcome. Every container not updated is logged as a warning with Dockhand's reason, since the error otherwise reaches only whoever started the install.
- After the job: one awaited `async_refresh_environment`, then the precise check (environment-wide; Dockhand has no per-container check) in the background, at most one running and one queued per environment.
- Progress lives in the installer, keyed by current container id, announced with `install_signal`, so an update entity shows it whichever path started the install. `PARALLEL_UPDATES = 0` in `update.py` lets HA's concurrent Installs reach the queue together.

## 4. Config entry migrations

The entry schema is **2.3** (`SCHEMA_VERSION` 2, `SCHEMA_MINOR_VERSION` 3 in `const.py`; the config flow's `VERSION`/`MINOR_VERSION` take them). `entry.data` holds only the connection (URL, token, SSL verification); everything the Configure dialog sets is in `entry.options` (`OPTION_KEYS`). Read settings from `entry.options` only.

**Downgrades work to the previous schema version only.** A 2.3 entry loads on every 2.2 release, not on 2.1. Each schema bump moves that window by one, so the only old setting names kept for downgrades are the latest change's.

**A minor schema bump for ordinary releases; a major only in a major release (X.0.0).** HA refuses an entry whose *major* version is newer than the code before the integration runs, but passes a newer *minor* to `async_migrate_entry`.

| | Next schema minor (2.2 → 2.3) | Next schema major (2.x → 3.1) |
|---|---|---|
| Integration release | any minor or patch | a major only |
| Downgrade one schema version back | works, settings kept | refused by HA: say so in the CHANGELOG |
| Downgrade two or more back | refused (`async_migrate_entry`) | refused |
| Stored old-name copies | this version's renames only | none |
| Upgrade from an older entry | yes, however many releases skipped | from the previous schema major only |
| Rename code (`RENAMED_OPTIONS`) | kept | deleted two schema majors later (a test fails until it is) |

Stored config thus never carries more than one version's renames, and code keeps one `RenamedOption` line per rename until two majors later. "One schema version back" is the smallest window that always covers "the release I was on before": the code can't tell how old a release is, and a schema version changes only when stored settings do. Releases before 1.11.0 (schema 2.1) accept any newer minor, so a 2.3 entry loads there with defaults for the settings 1.11.0 renamed; released code can't be changed.

**How it's built:** each rename is a `RenamedOption(old, new, major, minor)` in `RENAMED_OPTIONS`, each removal a `RemovedOption`. From the current `SCHEMA`:

- `renames_to_translate()`: renames from the current or previous schema major, translated on upgrade.
- `renames_to_mirror()`: renames made at exactly the current version (except a major's first minor, which nothing older can load). The old name is saved beside the new one, so the previous release keeps the user's value; it can't be taught to read new names, so this release writes old ones. Verified against released 1.10.2 with a 2.2 entry.
- `removed_to_keep()` / `removed_to_drop()`: a removed setting's value stays for the previous release until the next bump deletes it.
- `async_migrate_entry` refuses (returns `False`, logged) an entry more than one schema major old (remove and re-add) and one two or more minors newer (its release no longer writes the old names this code reads).
- `test_no_retired_renames_left_in_the_code` and `test_no_retired_registry_migrations_left_in_the_code` fail once a rename or registry migration is two schema majors old.
- Registry migrations (`migration.py`, `REGISTRY_MIGRATIONS`) record the schema major they upgrade from and follow the same rule; schema 1 installs can still upgrade, so they all stay until the next major. One of them re-enables container stats entities that releases before 1.8.0 left disabled by the integration: `RegistryEntryDisabler.INTEGRATION` means a default disabled it, never the user (`USER`), so only those are touched.

`_normalized_entry_config()` (`__init__.py`) applies it all: translates old names, moves settings from `entry.data` to `entry.options`, refreshes old-name copies. It runs from `async_migrate_entry` **and on every setup**: after a downgrade and re-upgrade the version is already current, so this is what picks up changes made while downgraded, and it restores the old-name copies after Configure saves (a saved options flow replaces `entry.options` with the form's fields). An old name present beside its new one wins (only an older release could have written it); a setting in both `data` and `options` takes `options`. It's pure and idempotent and runs before the update listener is registered, so it never triggers a reload.

**What a change needs:**

- A new setting with a safe default: nothing.
- A rename: a `RenamedOption` with the new version, bump `SCHEMA_MINOR_VERSION`. If the value's *format* changed, a plain copy under the old name is wrong: convert it, or don't mirror it so the old release uses its default. Renaming a label or a Python constant is free.
- A removal: drop it from `OPTION_KEYS`, add a `RemovedOption`, bump the minor.
- A major bump (major release only): bump `SCHEMA_VERSION`, minor to 1, delete what the two tests above list, and say in the CHANGELOG that downgrading below this release means removing and re-adding the integration.
- Anything else: a step in `async_migrate_entry` gated on `(entry.version, entry.minor_version)`.

History: 1 → 2.1 (1.8.0) renamed `enable_updates` → `enable_precise_updates`; 2.1 → 2.2 (1.11.0) renamed `enable_container_stats` → `enable_resource_stats` and the two polling intervals, and moved settings releases before 1.7.1 kept in `entry.data`; 2.2 → 2.3 (2.0.0) removed the polling intervals, since HA doesn't let users set them. Credentials from before API tokens (`_LEGACY_CONF_*`) aren't migrated: setup asks for a token and drops them.

**Only for transitions between released versions,** config and registry alike. Something added and removed within one unreleased cycle needs no migration (development reinstalls rather than upgrades); mention any orphan so it can be deleted by hand. And when a design changes after "no migration needed" was concluded, check again against the new design.

**An entity removed and re-created comes back with its old `disabled_by`** (HA's `DeletedRegistryEntry`, to keep user choices across reloads). That can't tell a user's choice from a stale default, so only `RegistryEntryDisabler.INTEGRATION` is ever cleared, never `USER`: see `async_enable_runtime_controls()` (§10) and the registry migration above.

## 5. Before finishing a change that adds entities

1. §0: any computed `device_info` field built by the shared factory, with a repeated `_ensure_env_devices()` test?
2. §1: every new unique ID matches its closest analog?
3. §2: every conditionally present entity has its live set and cleanup branch, tested for removal and for preservation offline or after a failed poll?
4. §4: a stored option's key changed? Then a migration.
5. §12: every changing value its own entity, every attribute always present?

None of these fail loudly.

## 6. Dockhand's behavior, not assumptions

- **Use Dockhand's own fields over recomputing them:** `systemContainer` rather than matching image names, stack resource stats from `GET /api/stack-stats` (1.0.52+) rather than summing container stats, so values match Dockhand's pages. An endpoint an older Dockhand lacks answers 404 (`DockhandNotFoundError`): treat that as "not supported" (create nothing, remove what exists), distinct from a failed fetch (keep everything, unavailable), as the fast coordinator's `stack_stats` does.
- **Check Dockhand's frontend, not just the route, for anything users see.** The frontend decides labels, icons, defaults and which controls appear: a stack with no source record is `sourceType: 'external'`, labelled "Untracked" (`getStackSource()` in `routes/stacks/+page.svelte`); the internal stack button is titled "Redeploy"; the git stack button is one action labelled "Deploy" when the stack is down and "Sync from Git" when it's up, which `DockhandGitStackDeployButton` mirrors with live name and icon. Dockhand doesn't version its terminology, so expect drift.
- **Feature-detect rather than compare versions.** Dockhand has no general version endpoint for gating (the changelog's version is for display), so check for the field you need (`"updatesAvailable" in stack`). It works on any version and adapts if Dockhand changes again.
- **Review a Dockhand release from its source:** `git diff vX vY -- src/routes/api/ src/lib/server/` and `static/openapi.json`, not the release notes, which have listed existing endpoints as new.
- **Check both resource types really support a feature before promising symmetry.** No git deploy path takes a per-call "pull images" flag (that's the stored `repullImages` setting), unlike internal stacks.

## 7. `dict.get(key, default)` doesn't cover an explicit `null`

`.get(key, {})` substitutes the default only when the key is absent. Dockhand sends explicit `null`s for optional data (`metrics`, per-environment slices, container stats), and the next chained `.get()` or `.items()` raises `AttributeError`. This was the codebase's most common bug (issue #20, and about 30 call sites when audited).

- **Use `or` at every level:** `(d.get(key) or {}).get(next_key)`.
- Read coordinator data through `_coordinator_env()` / `_all_envs()` (§8).
- Only data from outside needs this: a dict built locally from values already checked with `isinstance` (`all_stats` in the fast coordinator's `_fetch_env`) is safe.
- When one crash of this kind turns up, audit for the pattern, not just the reported line.

## 8. One data shape and one accessor for all coordinators

The fast, slow and update coordinators' data are all `{"environments": {env_id: {...}}, ...}`; `_coordinator_env(data, env_id)` and `_all_envs(data)` in `helpers.py` are the only accessors. When a shared shape or helper changes:

- Grep every read of each coordinator's `.data`, not just the tested ones. A consumer without tests (diagnostics' update summary once) keeps running and silently reads nothing.
- Check each call site's actual variable: `self.data` reads the same whatever coordinator `self` is.
- Unwrap `"environments"` in one place per variable, at assignment or at each read, never both: unwrapping twice returns empty without an error.

## 9. A successful poll can contain a failed fetch: `fetch_failures`

Both the fast and slow coordinators gather their per-environment calls with `asyncio.gather(..., return_exceptions=True)`, so one failing call doesn't fail the poll. But an empty result from a failed call must not look like a confirmed-empty resource, or cleanup deletes everything it backed (a schedules fetch failure once removed every schedule device).

- **`_unwrap()`** records which resource failed in a `failures` set, surfaced as `fetch_failures`: top-level in the slow coordinator (schedules, environments) and per environment in both (fast: containers, stacks; slow: images, networks, volumes, git stacks, runtime config, vulnerabilities, host, auto-update settings, recent events). Any new fetch in either coordinator threads through `_unwrap()`'s `failures`/`key` the same way.
- **`_build_live_sets()`** trusts an empty list only from a fetch that succeeded: `schedules_enabled` requires `"schedules"` not to have failed, and the `*_fetch_ok_env_ids` sets (images, networks, volumes, git stacks, stacks, containers) gate every removal. A whole environment failing in the slow coordinator leaves it out of `environments` for the cycle, so it's in none of those sets and nothing of it is removed.
- **A list Dockhand returned isn't trusted on first sight either.** Its containers, stacks and images routes answer 200 with `[]` when Docker is unreachable, and a container being recreated briefly drops out (likelier to be seen now that events trigger refreshes). `_RemovalGuard` (`coordinator.py`) requires whatever disappeared to still be missing on the next poll or refresh, and an empty list also needs Dockhand's own total in the dashboard stats not to be above zero. Until then the resource is in the environment's `unconfirmed`, which cleanup treats like a failure but which raises no repair issue (an environment without stacks is unconfirmed for one poll after every start). Volumes, networks and git stacks return 500 on a Docker error and aren't recreated, so they don't need it. Removal and re-adding would mostly be harmless anyway (the registries restore a unique ID's entity ID, disabled state, area and name); the guard prevents flicker and automations seeing it.
- **Values, not existence:** runtime config, vulnerabilities, host, auto-update settings and recent events never decide whether something exists, but a failure would show a wrong value (0 vulnerabilities for "unknown"). `BaseSlowEnvSensor._fetch_failure_key` names the resource a sensor depends on, and its `available` checks it (vulnerability sensors, host sensors, Hawser version); the runtime-control numbers and selects and the auto-update switch check `fetch_failures` in their own `available`. `recent_events` is the exception: the activity sensor's state comes from the fast coordinator, so only its `recent_events` attribute becomes `None` (not `[]`) when that fetch failed.
- **The update coordinator doesn't use `fetch_failures`:** on a per-environment failure it keeps that environment's previous data, and Tier 2 never decides existence anyway.
- **Repairs:** `_sync_fetch_issues()` runs after every slow fetch and keeps one repair issue for top-level failures (`{entry_id}_fetch_failed_top_level`) and one per affected environment (`{entry_id}_fetch_failed_env_{env_id}`), each listing every failing resource, removed as soon as the fetch succeeds. One issue per scope rather than per resource, so an outage isn't a wall of near-identical issues. Nothing is raised without a config entry (tests only).

**Recreating removed entities: `already_registered()`.** Every platform checks `helpers.already_registered(hass, known_ids, domain, unique_id)` with `entry.runtime_data.known_entity_ids` before creating an entity.

- The set is made fresh by each `async_setup_entry`, because the live entity objects are: an entity must be handed to `async_add_entities()` again after every reload, whatever the registry remembers. A set that lives longer (or one per platform that's never cleared) leaves an entity cleanup removed never coming back until a restart.
- The registry is never the primary check: it persists across reloads, so it says "already registered" for everything after the first setup and nothing would ever get its live object back. It's consulted only on a hit, to confirm an entity this session added is still there; if cleanup removed it since, the id is forgotten and the entity created again.
- Every platform with `async_setup_entry` uses it. When auditing, look for the shape (a set filled once and checked before creating an entity), not a variable name.

## 10. Turning disabled-by-default types on for every device

An entity that exists without any option may be created disabled, and then belongs in these sections. An entity that exists only because an option is on (images, volumes, networks, schedules, update entities, stats, runtime controls) is created enabled, since turning the option on is the choice to have it.

The options' **Environment / Container / Stack entities** sections (collapsed `section()`s; labels under `options.step.init.sections.<section>.data`, where the frontend looks for a field in a section) store `enabled_entities: {kind: [translation_key, …]}`. `entity_defaults.py` lists the types per kind (`OPTIONAL_ENTITIES`), keyed by translation key; the selector labels are the entities' own names, copied into `selector.<kind>_entities` per locale.

- **New entities:** every platform's `async_setup_entry` wraps `async_add_entities` with `enabling_chosen()`, which sets `entity_registry_enabled_default` on the chosen types. A device's kind comes from its identifier.
- **Existing entities:** saving the options calls `async_apply_choice()` with old and new options. A newly chosen type: entities disabled by the integration are enabled; ones the user disabled stay off. A type no longer chosen: every enabled one is disabled by the integration, including any enabled by hand, since the registry records who disabled an entity but not who enabled it (the help text says so). Unchanged types aren't touched.
- **Runtime controls** are created enabled. HA restores a removed and re-created entity with its old `disabled_by`, so turning the option off and on would bring them back disabled; `async_enable_runtime_controls()` runs on every setup and enables those disabled by the integration (never by the user, and not while the entry's "Enable newly added entities" is off).
- **Adding a type:** its translation key to `OPTIONAL_ENTITIES` and its name to every locale's `selector.<kind>_entities` (tests check both).

## 11. Environment settings as entities

`env_settings.py`: switches and selects for an environment's own settings, one `EnvSettingDescription` each (`read`, `field`, `write`, `write_field`, `requires`, `unique_suffix`), defined in the platform files. Reads cost nothing new where the dashboard stats already carry the flag.

| Setting | Read | Written |
|---|---|---|
| Activity, metrics collection | dashboard stats (fast poll) | `PUT /api/environments/{id}` (partial) |
| Update checks, auto-update | dashboard stats (`updateCheckEnabled`, `updateCheckAutoUpdate`) | `POST …/update-check`, which replaces every field: re-read first, change one |
| Image pruning, prune mode | `GET …/image-prune` (slow poll) | `POST …/image-prune`, same |
| Vulnerability scanner | `GET /api/settings/scanner?env=&settingsOnly=true` (slow poll) | `POST /api/settings/scanner` (partial) |
| Default scanner (Dockhand device) | the same without `env` (slow poll) | the same without `envId` |
| Event collection mode and poll interval (Dockhand device) | `GET /api/settings/general` (slow poll) | `POST /api/settings/general` (partial) |

- After a change, a stats-read setting requests a fast refresh; the others await `async_refresh_env_settings()` (or `async_refresh_scanner_default()`, which also re-reads every environment's scanner, since one without its own follows the default). A scanner change also requests a fast refresh, because the Vulnerability scanning sensor reads `scannerEnabled` from the dashboard stats. A failed read keeps the previous value; a setting never read (no permission) stays absent, so no entity is created.
- Auto-update is unavailable while update checks are off: Dockhand reports it off then, and it has no effect.
- Entities are added from fast and slow listeners as their setting becomes readable; they're configuration entities, enabled by default. A token that can read but not change a setting still gets the entity; changing it reports Dockhand's "permission denied". Dockhand can't tell a token what it may change (`/api/auth/session` answers browser sessions only), and only its Enterprise edition restricts permissions at all.
- They replaced the 1.x binary sensors with the same unique IDs and translation keys; `_cleanup_stale_registry` removes the old entities (`_RETIRED_ENV_BINARY_SENSORS`), and the cards, which read on/off by translation key, needed no change. Vulnerability scanning stays a binary sensor: its control picks a scanner, not on/off.
- Not exposed: Dockhand's disk-space warning; the Disk usage sensor lets an automation do the same.
- Unique ID suffixes avoid cleanup's type words (`image_prune_mode` is `prune_mode`), or are listed in `_TYPE_COLLISION_EXCLUDED_SUFFIXES`.

## 12. Entities, not attributes

Home Assistant's guidance ("State and attributes"): before adding an attribute, ask whether it should be an entity. Attributes get no long-term statistics, can't feed the energy dashboard and aren't translated as easily, so a value that changes on its own is its own sensor. Static facts about a device go in its device info. An expected attribute is always present, None when empty, not coming and going. Every attribute change writes a state row, so nothing that changes on every update belongs in one.

- **Counts and sizes are sensors.** An environment's containers and stacks by state, update counts by kind (`_pending_update_counts`), memory used and total, each part of disk usage, today's activity events, vulnerability counts by severity and images scanned (`ENV_VALUE_SENSORS`, `VULNERABILITY_SENSORS`); a container's memory cache; a stack's running containers and update count.
- **Attributes describe the state** and don't change on their own: a container's image, networks, exit code; a stack's type; an image's tags and labels; a schedule's last run. Lists (`recent_events`, `top_containers`) stay attributes, unrecorded.
- **Nothing churns.** Docker's status text ("Up 3 hours") isn't on the State sensor; host last boot keeps its value unless the computed time moves by over a minute; Hawser Edge's last check-in is its own sensor, disabled by default.
- **No name attributes.** The device names an entity: the cards take a container's or stack's name from its device identifier, an environment's from its device, a schedule's from its device name.
- **Static facts on the device:** a container device's `sw_version` is its image's version (the OCI version label, else the tag; none for a digest reference), updated by a listener.
- **Defaults:** sensors the cards draw from (container and stack states, the update counts the Environment card shows, memory used and total) are enabled; the rest are disabled and listed in the bulk sections (§10).
