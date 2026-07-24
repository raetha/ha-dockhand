# Architecture reference

This is the reference to check **before** adding any new entity, device, or
config option — not after. It exists because this codebase has non-obvious
conventions and a central lifecycle system that are easy to miss by reading
any single platform file in isolation, and getting them wrong silently
breaks entity cleanup or collides with existing IDs rather than raising an
error. If you're adding something new and skip this doc, you are the most
likely person to reintroduce the exact bugs it documents.

## 0. Device registration has two call sites — sharing one set of factories

For containers, stacks, and environments, `DeviceInfo` gets written to the
device registry from **two independent call sites**, which run at different
times:

1. **Per-entity, via `device_info`.** Confirmed from Home Assistant's own
   developer docs: these properties "are read each time the entity is
   added to Home Assistant" — meaning **only the first time** that
   specific entity is ever added, never again on subsequent coordinator
   refreshes.

2. **`_ensure_env_devices()`/`_ensure_hub_devices()` in `helpers.py`.**
   Explicitly designed — per their own docstrings — to be safe to call on
   **every coordinator update**, calling `registry.async_get_or_create()`
   directly. This bypasses entities entirely; it's how devices get
   created/kept current even before any entity for them exists, and how
   `via_device` parents get set up before children need them.

Home Assistant's device registry explicitly overwrites `manufacturer`/
`model`/`name` on every `async_get_or_create()` call where they're
provided — that's by design, not a bug in HA. So if these two call sites
ever compute a field's value *differently*, whichever one runs later wins,
silently, no error. **This already happened once**: the stack device's
`model` was added to call site 1 (via `_stack_device()`, computed from
`sourceType`) without updating call site 2 (which kept a hardcoded generic
value). Result: the correct model showed immediately after a reload (call
site 1 ran first, at entity-add time), then got silently clobbered by call
site 2 on the very next coordinator update — looking like a mysterious
intermittent bug rather than the deterministic overwrite it actually was.

**Fixed by consolidating, not by "keeping two copies in sync."** Both call
sites now build every `DeviceInfo` by calling the *same* shared factory
function (`_env_device()`, `_container_device()`, `_stack_device()`,
`_containers_group_device()`, `_stacks_group_device()`,
`_network_group_device()`, `_image_group_device()`,
`_volume_group_device()` — all in `helpers.py`) — `_ensure_env_devices()`
calls them via `registry.async_get_or_create(config_entry_id=..., **factory(...))`
rather than duplicating their field construction inline. There is now
exactly one place that computes each device's fields; the two call sites
just differ in *when* they run, which no longer matters for correctness.

**When adding a new device type or a new dynamically-computed field**:
add or extend the shared factory function first, then call it from *both*
sites — never write `DeviceInfo` fields inline in `_ensure_env_devices()`/
`_ensure_hub_devices()` directly, even for what looks like a one-off. Write
a test that calls the `_ensure_env_devices()` path **repeatedly** with the
same input — matching how it's actually used in production — not just
once; a single-call test won't catch a field that only drifts on a second
call.

## 1. Unique ID conventions

**Entity unique IDs:** `{entry_id}_{env_id}_{type}_{discriminator}`

`type` is always a single recognizable category word matching one already
in use — `container`, `stack`, `image`, `network`, `volume`, `update`,
`schedule`. **Never introduce a new compound type word** (e.g. `git_stack`,
`auto_update_switch`). If an entity is scoped to an existing category (a
container, a stack), its type word is that category's word, and whatever
makes the entity distinct goes entirely in `discriminator` — including a
qualifying prefix if needed, e.g. `stack_{name}_git_sync_status`, not
`git_stack_{name}_sync_status`. This isn't just a style nit: cleanup code
in `__init__.py` parses `unique_id.split("_")[2]` as the type; a compound
type word splits across two array positions and breaks that parsing,
forcing special-case workarounds. (This mistake shipped once in the git
stack entities during 1.8.0 development and was caught and fixed before
release — don't reintroduce it.)

**Device identifiers:** `{DOMAIN}, "{type}_{env_id}_{name}"` — e.g.
`container_{env_id}_{name}`, `stack_{env_id}_{name}`, `env_{env_id}`. See
`helpers.py`'s `_container_device`/`_stack_device`/`_env_device` etc. —
always use these factories, never build `DeviceInfo` inline in a platform
file.

**Container identity is name-based, not ID-based**, on purpose: Docker
container IDs change on every recreation (image update, `docker compose
up` redeploy), but names are stable and Docker enforces their uniqueness
per host. Every container-scoped unique_id and device identifier uses the
container *name*. Same reasoning for stacks (Compose project name) and
git stacks (`stackName`, which — confirmed from Dockhand's source — is
always identical to the Compose project name for that same stack, since
`deployGitStack` passes it straight through as `docker compose -p
{stackName}`; this is *why* git stack entities can safely attach to the
same device as the regular stack entities without any duplicate-device
risk).

**Before adding a new entity type**, grep for how the *closest existing
analog* names its unique_id and copy that pattern exactly. Don't design a
new naming scheme from first principles.

**`translation_key` is a separate, cross-repo stability contract** —
unlike `unique_id`, don't treat it as free to refactor. The
[ha-dockhand-cards](https://github.com/raetha/ha-dockhand-cards) repo
resolves entities by `translation_key` + `platform: "dockhand"` scoped to
a device, specifically *because* `unique_id` is documented above as an
internal detail that can change. Renaming an existing `translation_key`
is a breaking change for that repo (and any user's own automations keying
off it) — if one genuinely needs to change, treat it like the
`CONF_ENABLE_UPDATES` → `CONF_ENABLE_PRECISE_UPDATES` rename (§4): a
deliberate, documented, migrated change, not a casual cleanup. Adding a
*new* `translation_key` is free; the cards repo's `resolveEntities` degrades
gracefully (treats it as "not yet available on this ha-dockhand version")
when a key it looks for doesn't exist yet.

## 2. Entity cleanup — read this before adding anything conditionally-present

**This codebase already has a comprehensive, central cleanup system.** It
is not something to build per-platform. It lives entirely in `__init__.py`:
`_build_live_sets` (computes what currently exists, from all three
coordinators) and `_cleanup_stale_registry` (removes anything no longer in
those sets), both called after every entry setup.

Two-part design:

1. **Device-registry pass.** Removes `container_`/`stack_`/`env_` devices
   (and, automatically, every entity attached to them, via Home
   Assistant's own device-removal cascade) when the environment they
   belong to is deleted, or the environment is confirmed online and the
   specific container/stack is confirmed gone. This handles the vast
   majority of entities for free — switches, sensors, buttons on a
   container or stack device disappear correctly with zero extra code,
   as long as the device itself is registered correctly.

2. **Entity-registry pass.** For entities that *don't* fit the device-
   cascade case. Two reasons an entity ends up here:
   - **Standalone** — no device of its own (images, networks, volumes
     live under a shared group device, not one per item).
   - **Conditionally present despite a persistent device** — the entity's
     existence depends on something other than "does the container/stack
     still exist." This is the case that's easy to miss. Examples:
     update entities (depend on the environment's `updateCheckEnabled`),
     runtime controls (depend on a config toggle **and** the container
     being stack-less), git stack entities (depend on Dockhand still
     classifying that stack as git-tracked). In every one of these, the
     container or stack device persists — only some of its entities
     should disappear.

**Every category in the entity-registry pass follows the same two-case
safety rule**, and any new one must too:
- Remove if the environment itself no longer exists (deleted from
  Dockhand).
- Remove if the environment is confirmed **online** and a successful
  poll confirms the specific item/condition is gone.
- **Never** remove on a failed poll, or while the environment is offline.
  That data isn't ground truth — a stale entity sitting around is a much
  smaller problem than deleting something that's still real and just
  temporarily unreachable.

**Checklist for adding a new conditionally-present entity type:**

1. Does it live on an existing device (container/stack), or does its
   existence depend on something that can change while that device
   persists? If yes to the second question, it needs entity-registry
   tracking — device cascade alone will not clean it up.
2. In `_build_live_sets`, add a new live-uid `set[str]`, built from
   whichever coordinator actually backs the entity's existence (fast
   coordinator for anything derived from the container/stack list or
   dashboard stats; slow coordinator for anything from images / volumes
   / networks / git_stacks / runtime_config — guard slow-derived sets
   with `slow_valid`).
3. Add a matching `elif` branch in `_cleanup_stale_registry`'s
   entity-registry pass, following the two-case rule above.
4. **Do not** build a separate ad-hoc removal mechanism inside that
   platform's own `async_setup_entry`. (This happened — wrongly — in
   `update.py`'s first draft during 1.8.0 development: it worked, but
   duplicated logic that already existed centrally, and was harder to
   audit for the two-case safety rule. It was removed in favor of
   extending the central mechanism once caught.)
5. Add test coverage in `test_init.py` mirroring the existing
   runtime-control/git-stack/update tests: entity preserved when live,
   removed when the condition flips, preserved when the environment is
   offline or the relevant poll failed.

**If you're doing a "did we implement X correctly" review of new work**,
explicitly check this file's cleanup logic against every new entity type
added — don't rely on general code review to surface this, since a
missing cleanup case produces no error, no failing test (unless you wrote
one specifically for it), and no visible symptom until a user actually
disables a feature or a stack stops being git-tracked.

**Watch for accidental collisions with the reserved type words.** The
entity-registry pass dispatches on `uid_type = unique_id.split("_")[2]` —
just the one word at that position, not the full suffix. An ordinary,
never-suppressed entity whose name simply *starts* with a reserved type
word (`image`, `network`, `volume`, `update`, `container`, `stack`) will
be caught by that type's branch and checked against its live-uid set —
and since it isn't actually that kind of entity, it will never appear
there, and gets silently removed on every online poll. This happened for
real: `{entry_id}_{env_id}_update_check_enabled` and
`{entry_id}_{env_id}_image_prune_enabled` — both ordinary always-on
binary sensors — collided with the "update" and "image" branches purely
because their names start the same way, and were removed within about a
minute of every reload, while still showing as present immediately after
loading. Fixed via `_TYPE_COLLISION_EXCLUDED_SUFFIXES`, an exact
full-suffix exclusion list checked before the dispatch runs. Before
naming any new entity, check whether its uid could start with one of the
six reserved words without actually belonging to that category — if so,
add its exact suffix to that list.

**A second, related collision type: two different conditionally-present
entity categories sharing an exact suffix within the same `uid_type`.**
The container-stats sensors (`sensor.py`'s 8 CPU/memory/network/
block-I/O entities) and the runtime-control entities (`number.py`/
`select.py`) both use `uid_type == "container"`, and one suffix is
identical on purpose: `memory_limit`. Unlike the collision above, adding
the shared suffix to `_TYPE_COLLISION_EXCLUDED_SUFFIXES` would be wrong
here — that list is for entities that should be *exempt from cleanup
entirely* (device cascade only), and both of these genuinely need their
own independent conditional tracking, just gated on different things
(`enable_container_stats` vs. `enable_runtime_controls` + stack-less).
Disambiguated by **entity domain** instead — the container-stats
sensor is `sensor`, the runtime control is `number` — checked in the
runtime-control `elif` branch before the suffix match, so a same-suffix
`sensor`-domain entity falls through to its own `container_stats_uids`
branch rather than being caught (and incorrectly removed) by the
runtime-control one. This shipped and was caught the same way as the
first collision — a container-stats entity disappearing right after its
first successful poll. Before reusing a suffix across two different
entity categories that share `uid_type`, either give them distinct
domains (as here) or distinct suffixes; don't rely on elif ordering
alone to keep them apart.

## 3. Coordinator architecture

**A coordinator update must fail (raise `UpdateFailed`) on a total fetch failure — never catch
the exception and return an empty-but-successful result.** Found the hard way (2026-07-14): the
fast coordinator's dashboard-stats fetch used to catch any exception, log a warning, and continue
with an empty environments list — reasoning that a transient failure "just skips this cycle."
But an empty *successful* result is indistinguishable from "there are genuinely zero
environments" to everything downstream that trusts non-empty coordinator data as authoritative,
including `_cleanup_stale_registry`'s own "fast data must be non-empty" guard (an empty
intermediate list still produced a non-empty `fast_coordinator.data`, since `_fetch_env` ran per
already-known env_id regardless — the guard didn't actually catch this). A DNS resolution
failure to the Dockhand host is exactly this scenario, and produced exactly this bug: stacks and
containers looked deleted, not offline. Raising `UpdateFailed` instead makes HA's own coordinator
machinery do the right thing for free — `coordinator.data` stays at its last-known-good value,
`last_update_success` goes `False`, entities report unavailable via the standard
`CoordinatorEntity.available` check, and (since `__init__.py` uses
`async_config_entry_first_refresh()`) a failure during setup/reload correctly surfaces as
`ConfigEntryNotReady`, not a silent success. The general principle: a coordinator's `_fetch()`
should only ever return "here's what I know is currently true" or raise — never "I don't know,
so I'll pretend it's empty."

**Same principle applies per-environment, not just to a coordinator's overall fetch — audited
all three coordinators for it (2026-07-14).** The update coordinator (`DockhandUpdateCoordinator`,
Tier 2 precise versions) had the identical anti-pattern at per-environment scope: a failed
`async_check_container_updates(eid)` call was caught and replaced with an empty list, which reads
as "confirmed zero pending updates" for that environment — flipping every container's update
entity there to "up to date" during a transient failure, rather than leaving their actual pending
status alone. Fixed by falling back to that environment's entry in `self.data` (the coordinator's
own last-known-good data) instead of an empty dict on failure. The slow coordinator's own
per-environment gather (`return_exceptions=True`, log-and-omit-that-env-this-cycle) was checked
too and is *not* the same bug — a genuinely missing dict key reads as "no fresh data this cycle,"
not "confirmed empty," and downstream slow-coordinator consumers already handle a missing env
gracefully rather than treating it as authoritative — but it's a narrower, more nuanced case
worth a closer look someday; noted in `docs/BACKLOG.md` rather than changed blind.

- `DockhandFastCoordinator` (60s): dashboard stats, containers, stacks,
  container resource stats, pending-update flags. This is also the sole
  source of which environments exist — no coordinator calls
  `/api/environments` for enumeration (see below).
- `DockhandSlowCoordinator` (600s): images, volumes, networks, schedules,
  runtime controls, git stacks, host info, auto-update settings, and
  env_meta (see below) — always fetched, cheap bulk calls. Also two
  *gated* per-env fetches, each keyed off a flag already present in the
  fast coordinator's dashboard-stats blob rather than a separate CONF_
  option: `recent_events` (GET /api/activity, only when `collectActivity`
  is on for that environment) and `vulnerabilities` (GET
  /api/vulnerabilities/count, only when `scannerEnabled` is on) — both
  feed sensor attributes (`sensor.activity_events`'s `recent_events`
  list, `sensor.vulnerabilities`'s severity breakdown) rather than their
  own dedicated coordinator-data top-level keys' sensors, since gating on
  a real Dockhand setting means an environment that doesn't use that
  Dockhand feature never pays for the extra call. Derives its own
  environment-id list from the fast coordinator's already-fetched data
  (fast completes its first refresh before slow starts, per
  `__init__.py`'s setup order) rather than making a call of its own.
- `DockhandUpdateCoordinator` (24h default, optional): only created when
  `CONF_ENABLE_PRECISE_UPDATES` is on. Purely additive — see below.

**`/api/environments` is never used for environment enumeration**, and
its raw response is never stored. It returns Dockhand's own secrets
(`tlsKey`, `hawserToken`) fully decrypted with no redaction on Dockhand's
side, so which environments exist is sourced instead from
`/api/dashboard/stats` (id/name/icon/connectionType/online/labels/
updateCheckEnabled) — that's what both coordinators actually enumerate
from. `labels` from this same blob is surfaced as `binary_sensor.online`'s
`labels` attribute — no extra fetch, since the fast coordinator already
has it for every environment on every poll. It's used for the one-time connectivity probe during config flow
setup (result discarded), and the slow coordinator does call it once per
600s poll for a narrow purpose: it's the only source for four fields
nothing else exposes — `imagePruneEnabled`, Hawser agent identity
(`hawserAgentName`/`Id`/`LastSeen`), and the environment's configured
Docker connection `host`/`port`. Only those four fields are ever
extracted into `env_meta` immediately on receipt; the raw response with
its decrypted secrets is discarded in the same breath, never stored in
coordinator state. If you add a new field sourced from this endpoint,
extend `env_meta`'s extraction the same way — never store the raw
response.

**Two-tier update entity pattern** (a template for future "cheap always-on
signal + optional expensive precision" features): `ContainerUpdateEntity`'s
*primary* coordinator is the fast one, not the optional update coordinator
— Tier 1 (existence, `installed_version` as image tag, `update-pending`
signal from a cheap DB-read endpoint) works completely with Tier 2 absent.
Tier 2, when present, is consulted directly (not as a primary coordinator)
purely to upgrade `installed_version`/`latest_version` to precise digests
on the *same* entities — it never gates *this entity's* creation or
removal. If you build another feature with this "free basic signal, paid
precise signal" shape, follow this same structure: cheap tier owns entity
lifecycle, expensive tier is a pure data enrichment layered on top.

**The whole platform sits behind `CONF_ENABLE_UPDATE_ENTITIES`** (default
`True`, added for github.com/raetha/ha-dockhand/issues/23 — some users
manage container updates entirely outside HA and don't want these
entities in HA's own update management). This is a coarser, higher-level
gate than either tier: off means neither tier's ENTITIES exist, and the
bulk "Update all" button disappears too, since with entities gone it
would otherwise be a backdoor to triggering real updates from HA despite
the user's explicit choice — the actual concern behind the issue. It
does NOT gate Tier 2's `update_coordinator` object, and it does NOT gate
the "Check for updates" button (`DockhandCheckUpdatesButton`) at all —
that button is read-only and unconditional: it always exists on every
environment device and always calls Dockhand's real check-updates API
directly against the client, regardless of either CONF_ENABLE_* option
or whether `update_coordinator` was even instantiated. What the options
control is only what happens to the *result* of that forced check —
see the button's own docstring in button.py for the full breakdown, but
briefly: if `update_coordinator` exists, the result also updates Tier 2
(`DockhandUpdateCoordinator.async_merge_check_results()`); if
`CONF_ENABLE_UPDATE_ENTITIES` is on, the result also immediately updates
Tier 1's `pending_update_container_ids` for that one environment
(`DockhandFastCoordinator.async_merge_pending_updates_from_check()`) —
no need to wait for that environment's next 60s poll to reflect a check
the user just explicitly forced. Neither merge happens if its
corresponding option is off; the check still runs either way (Dockhand's
own cache still gets refreshed server-side), just with nothing local
capturing the response. Tier 1's own regular, scheduled pending-updates
*fetch* is likewise NOT gated on this option,
for the same reason (other consumers legitimately want it regardless of
whether update entities are shown) — which means `pending_update_container_ids`
*and* Tier 2 data can both still be non-empty with the platform off.
Anything gating on "is there a pending update" for the purpose of
allowing an actual update action (specifically, the bulk button's
creation and cleanup) must therefore check `CONF_ENABLE_UPDATE_ENTITIES`
explicitly rather than assuming the absence of update entities implies
the absence of Tier 1/Tier 2 data.

The env-level bulk "Update all" button is also a deliberate exception to
"Tier 2 never gates lifecycle" one level down: it's an env-level
aggregate rather than a per-container entity, and both Tier 1 and Tier 2
are folded together (via the shared `_container_has_pending_update()`
helper in `helpers.py`) to decide whether it exists at all. This is safe
specifically because Tier 2 is always looked up by each container's
*current* id, never by name — see the next paragraph for why that
distinction matters.

**Consult Tier 2 (or any coordinator that persists data keyed by an id
that can change identity) by current id, never by name.** Real bug: an
earlier version of `ContainerUpdateEntity`'s Tier 2 lookup scanned
`update_coordinator.data` for an entry whose `containerName` matched,
discarding the dict's own `container_id` key in the process. Tier 2 only
re-polls on a slow schedule (default 24h); a container recreated in the
meantime (the normal effect of an image update) gets a new id, but its
*name* is stable across recreation — so the stale entry, describing a
container that no longer exists, kept matching by name and showing an
already-resolved update as still pending for up to a full Tier 2 cycle.
Fixed by looking the entry up as `env_data.get(current_container_id)`
instead of scanning by name: a stale entry's key is the *old* id, which
is never a key in the lookup for a container's *current* id, so it's
simply never found — self-invalidating by construction, no explicit
staleness check needed. Apply the same shape (lookup by current identity,
not a human-readable label that survives recreation) to any future
enrichment layer with its own independent poll cadence.

**Explicit user actions (button presses, switch toggles, an update entity's
install) must call `coordinator.async_refresh()`, never
`async_request_refresh()`.** The latter goes through
`DataUpdateCoordinator`'s built-in request-refresh debouncer (10s cooldown,
`immediate=True`), which has a real, non-obvious failure mode for anything
awaiting its result: if the debouncer's cooldown timer is still armed from
*any* prior refresh of that coordinator — another button press, or the
coordinator's own scheduled poll landing within the last 10s, both common
in practice (e.g. right after HA startup/reload) — calling
`async_request_refresh()` again returns almost immediately **without
running the refresh at all**. It just re-arms a background timer to run it
~10s later, fully detached from the caller. From the caller's perspective
(and a card's own "in progress" UI state awaiting the service call) that
looks exactly like something that ran and finished in under a second, when
nothing has actually happened yet. Found via a real user report: the
"Check for updates" button's card-side spinner clearing after ~2s while
the actual check kept running server-side for close to a minute.
`async_refresh()` skips the debouncer entirely — straight to the
coordinator's own lock, always genuinely runs — which is the correct
semantics for "the user pressed something now, actually do the thing and
tell me when it's done." Reserve `async_request_refresh()` for genuine
automatic/internal refresh requests (e.g. many entities' state-changed
listeners firing in quick succession, where coalescing is the whole
point) — this integration doesn't currently have one of those.

**That debounce fix was real and necessary, but not sufficient on its own
for the "Check for updates" button specifically — a second, unrelated
issue was hiding behind it.** `DockhandCheckUpdatesButton` is attached to
each environment's device, but calling `async_refresh()` on
`DockhandUpdateCoordinator` always re-checks *every* environment in one
gather (that's genuinely the right behavior for the coordinator's own
periodic background refresh). Pressing environment 1's button was
therefore silently also re-checking environments 2 and 3 — confirmed with
live timing logs during the same debugging session: 4 environments, 4
buttons pressed via the card's "check all" action, and each press queued
a fully redundant re-check of all 4 environments behind the same
coordinator lock (~20 HTTP calls where ~4 would do, and climbing
per-press latency as each queued behind the last). Fixed by giving the
coordinator a genuinely-scoped `async_check_environment(env_id)` method
(built on `async_set_updated_data()` — see its own docstring in
coordinator.py) instead of routing the button through the coordinator's
own all-environments refresh at all. The lesson: a debounce/timing fix
that resolves the *symptom* (spinner clearing early) doesn't necessarily
mean the *design* (what actually runs when this specific entity is
pressed) was right to begin with — worth checking both.

**Postscript (1.8.1):** `async_check_environment()` still exists and is
still exactly this env-scoped fix, but `DockhandCheckUpdatesButton`
itself no longer calls it — see the `CONF_ENABLE_UPDATE_ENTITIES`
section above. The button now needs the raw check-updates response
itself (to conditionally feed Tier 1 as well as Tier 2), so it calls the
client directly and hands the response to the new
`async_merge_check_results()`, which `async_check_environment()` itself
now also delegates to. Same env-scoping fix, same underlying mechanism,
just split so the merge step can be reused with a response the caller
already has in hand instead of always re-fetching.

## 4. Config entry migrations

`DockhandConfigFlow.VERSION` (currently 2) must be bumped whenever
`entry.data`/`entry.options` schema changes in a way existing stored
entries can't tolerate: a key renamed, a key removed, or a key added with
no safe default. A key added *with* a safe default does not need a bump.
Renaming a config option's `strings.json` display text or its Python
constant name is free (both are cosmetic); renaming the underlying string
*value* used as the dict key is not, and needs a migration.

`async_migrate_entry(hass, entry)` in `__init__.py` is the mechanism —
standard Home Assistant pattern, checks `entry.version`, transforms
`entry.data`/`entry.options`, calls
`hass.config_entries.async_update_entry(entry, data=..., options=...,
version=new_version)`. The 1.8.0 cycle's `enable_updates` →
`enable_precise_updates` rename is the first (and, as of this writing,
only) example — copy that pattern for the next one rather than inventing
a new approach. (A second, 2 -> 3 step briefly existed in an unreleased
1.8.1 dev cycle, grouping `enable_precise_updates`/`poll_interval_updates`
into a `section()` alongside the new `enable_update_entities` — reverted
before release after the section's field labels wouldn't render
correctly in a live instance and the exact cause couldn't be confirmed
from source alone; see docs/BACKLOG.md. Nothing shipped at version 3, so
there was nothing to migrate away from — `VERSION` went back to 2 and
the 2 -> 3 step was deleted outright rather than kept as a dead migration
path.) (The 1.2.0 session-cookie removal used a different, force-reauth-inline approach
because that migration genuinely required
user interaction — a straightforward value-preserving rename does not,
and should use the formal `VERSION`/`async_migrate_entry` mechanism
instead.)

**Only for transitions between released versions.** The same rule
applies to entity/device registry migrations in `migration.py` — never
add one for something that was only ever added and removed within the
same still-unreleased dev cycle (an interim build's entity that never
shipped). Development testing here reloads/re-adds the integration
rather than upgrading in place, so a migration for that case is pure
maintenance cost for zero benefit — mention the orphaned entity in your
response instead, so it can be deleted by hand if needed.

**Re-verify a "no migration needed" conclusion if the underlying design
changes after that conclusion was reached.** A conclusion like "existing
registry entries are unaffected by this option" is scoped to the design
as it existed at the time it was checked — if a later change alters
*how* those entries get created (e.g. moving from "always created,
enabled-state varies" to "only created when the option is on"), the
earlier analysis doesn't automatically still hold. Re-check against the
new design rather than assume the earlier "no migration needed" verdict
carries forward.

**An entity removed by our own cleanup and later recreated with the
same unique_id can come back still disabled — this is HA's own
behavior, not a bug to route around with `_attr_entity_registry_enabled_default`
alone.** Home Assistant keeps a `DeletedRegistryEntry` for a removed
entity and, when `async_get_or_create()` sees the same
`(domain, platform, unique_id)` again, restores its prior `disabled_by`
— deliberately, to preserve a user's customization across an
integration reload or a brief entity absence. The problem: this can't
distinguish "the user chose to disable this" from "this was only ever
disabled because of a stale default from before some option existed, or
from a previous toggle-off removing it." Real, reported symptom: the
container-stats entities (conditionally created — see §2) staying
disabled after being toggled off and back on, even though they're meant
to default to enabled now. Only a targeted fix works, not a broad one:
check the entity's actual `disabled_by` reason specifically —
`RegistryEntryDisabler.INTEGRATION` means "disabled because the entity's
own enabled-by-default flag said so," never a deliberate user choice
(that's `RegistryEntryDisabler.USER`) — and only clear the former.
Blindly re-enabling everything on every setup would silently overwrite
genuine user choices; only doing this once (as a migration) wouldn't fix
the *next* toggle-off/toggle-on cycle, since the underlying HA behavior
recurs every time, not just once at upgrade. See
`_reenable_stale_container_stats_entities()` in `sensor.py`.

## 5. Before finalizing any session that added entities

Walk through, in order:
1. Section 0 — did you add or change any dynamically-computed
   `device_info` field (not just a static one like `manufacturer`)? If
   so, is it built via the shared factory function (not written inline
   in `_ensure_env_devices()`/`_ensure_hub_devices()`), and is there a
   test that calls `_ensure_env_devices()` repeatedly?
2. Section 1 — does every new unique_id match an existing analog's
   pattern?
3. Section 2 — does every new conditionally-present entity have a
   matching branch in `_build_live_sets`/`_cleanup_stale_registry`,
   with test coverage for both the removal case and the
   offline/failed-poll preservation case?
4. Section 4 — did any config option's underlying key change? If so, is
   there a migration?

Getting any of these wrong doesn't fail loudly. It leaves users with
entities that silently never clean up, or (worse) an entity ID that
collides with or shadows another one. Treat this document as a required
review step, not optional background reading.

## 6. Verifying against Dockhand's actual behavior, not assumptions

**Prefer Dockhand's own precomputed, authoritative API fields over
replicating its client-side logic**, whenever both are available — e.g.
a container's `systemContainer` field (Dockhand's own classification)
over regex-matching image names ourselves. Safer against drift (Dockhand
can change its own classification rules without us noticing) and
simpler to maintain.

**Check the frontend, not just the API route, for anything user-facing.**
A field can be genuinely absent from a server response in a case
Dockhand's own frontend still has well-defined, deliberate handling
for — e.g. `getStackSource()` in `routes/stacks/+page.svelte` treats a
missing source record as `sourceType: 'external'` and labels it
"Untracked" in the UI, which the server route alone gives no hint of.
Reading only the server route and inferring "absent means unknown, use
a generic fallback" produced a real, shipped-then-caught bug (the stack
device's `model` incorrectly defaulted to a generic label instead of
"Untracked Stack" until this was caught). This applies to labels, icons, default values, and which
UI controls appear for which state — the frontend is the actual source
of truth for what a user should see or do; the API route only tells you
what data exists. Two more confirmed examples: the internal-stack
redeploy button's literal title is "Redeploy" (from
`RedeployPopover.svelte`'s own `title` attribute), not "Deploy"; and the
git-stack action button isn't two different actions with different
names — it's one button (`GitDeployProgressPopover`) that relabels
itself "Deploy" (stack down) vs "Sync from Git" (stack up) while calling
the identical underlying function either way, confirmed from
`stacks/+page.svelte`'s conditional around it. `DockhandGitStackDeployButton`
mirrors that exact relabeling (name and icon) via live `@property`
lookups against the fast coordinator's stack status — copy that pattern
if another entity needs the same kind of Dockhand-state-dependent
identity. **Dockhand has no versioning scheme for its own UI/API
terminology** — if a future review finds label or iconography drift
from what's documented here, that's expected to happen eventually, not
a bug in this integration.

**Prefer feature detection over version comparison when gating on a
Dockhand capability.** Dockhand has no clean, non-admin API endpoint
that returns its own app version for general querying (the only
version-related endpoint, `/api/self-update/check`, is admin-only and
tied to image-tag parsing for Dockhand's own self-update workflow).
Check whether the specific field/key you need is actually present in
the response instead — e.g. the stack "Updates available" sensor checks
`"updatesAvailable" in stack`, not a Dockhand version number. This works
correctly against any Dockhand version without a version-parsing
utility, and self-adapts if Dockhand changes the field again later.

**When evaluating what's new in a Dockhand release, diff the actual
source** (`git diff vX vY -- src/routes/api/` and the relevant
`src/lib/server/*.ts`) rather than trusting a summarized changelog or
release notes. Doing this caught two false leads during the 1.0.37
review: a "new" `GET /api/containers/check-updates` endpoint that
turned out to be a byte-for-byte duplicate of one already in use, and
"stack-level update support" that turned out to be an existing
(~1.0.23) redeploy endpoint newly exposed in the UI with update badges,
not a new endpoint at all.

**Verify equivalent capabilities actually exist across resource types
before assuming symmetric UX is achievable.** Git stacks and internal
stacks look like parallel concepts, but Dockhand's API doesn't treat
them symmetrically: no git-deploy code path (checked all of them —
`deployGitStack`, `deployGitStackWithProgress`, both the sync and
streaming routes) accepts a parameter to force a fresh image pull —
that's governed entirely by a stored per-git-stack `repullImages`
setting with no per-call override. Before designing a feature that's
supposed to behave the same way across two resource types, check the
actual function signatures for both, not just that similarly-named
endpoints exist.

## 7. `dict.get(key, default)` is not null-safe against an explicit `null`

**The single most-recurring bug class in this codebase, found via a real
crash and a previously-open GitHub issue
(github.com/raetha/ha-dockhand/issues/20) that turned out to share the
same root cause.** `dict.get(key, default)` only substitutes `default`
when `key` is *absent*. If Dockhand's API response has the key present
with an explicit `null` — which it does for optional/runtime data
(`metrics`, `container_stats`, a specific environment's slice of
per-env data, etc.), not just when a value is omitted — `.get(key, {})`
returns that `None`, not `{}`, and the very next chained `.get()`,
`.items()`, `.values()`, or `.keys()` call crashes with
`AttributeError: 'NoneType' object has no attribute '...'`.

The original GitHub issue reporter guessed this was specific to stopped
containers with CPU/memory tracking enabled. It wasn't — the same
pattern independently crashed an *environment*-level sensor too, tied to
`metrics` being null on that environment's stats blob specifically, with
no container involved at all. When you see one instance of this crash,
audit for the pattern generally rather than patching just the one
reported call site — this session found roughly 30 vulnerable call
sites across nearly every platform module once the first one was
tracked down, most never reported because they hadn't been hit yet.

**The fix is `or`, not a second `.get()` default**, at *every* level of
a chain, not just the outermost: `(d.get(key) or {}).get(next_key)`, not
`d.get(key, {}).get(next_key)`. `or` correctly substitutes the fallback
whether the key is absent or present-but-null; a `.get()` default only
covers the absent case.

**Two exact patterns were duplicated near-identically across six-plus
files** — `slow_data.get("environments", {}).get(env_id, {})` and (at
the time) `fast_data.get(env_id, {})`, since the fast coordinator's data
didn't have the "environments" wrapper yet — strong signals that a
shared helper was overdue rather than another find-and-replace across
copies. `_slow_env(slow_data, env_id)` and `_fast_env(fast_data,
env_id)` in `helpers.py` were that helper at the time; both have since
been merged into one `_coordinator_env()` — see §8 for the full story
of why keeping them separate stopped making sense once all three
coordinators shared the same shape.

**Not every `.get(key, {})` in this codebase is actually vulnerable —
check before reflexively "fixing" one.** `all_stats.get(eid, {})` in
`coordinator.py`'s `_fetch_env` is safe as written: `all_stats` is built
locally via `{s["id"]: s for s in all_stats_list if isinstance(s, dict)
and "id" in s}`, so every value it can possibly contain already passed
an `isinstance(s, dict)` check — there's no code path that could put a
`None` there. The vulnerability is specifically about *trusting external
API response shape*, not about dict access in general.

## 8. All three coordinators now share one data shape and one accessor

`DockhandFastCoordinator.data`, `DockhandSlowCoordinator.data`, and
`DockhandUpdateCoordinator.data` are all `{"environments": {env_id:
{...}}}` — fast was `{env_id: {...}}` directly until this session;
update followed the same way shortly after. `_coordinator_env(data,
env_id)` and `_all_envs(data)` in `helpers.py` are the one accessor pair
now used everywhere, replacing what used to be `_fast_env`/`_slow_env`
(two near-identical functions) plus a parallel, inconsistently-applied
pattern of unwrapping "environments" inline at a local variable's
assignment point. This was deliberately deferred once (logged in
`docs/BACKLOG.md`, since removed now that it's done) until the timing
was right — pre-release, with the null-safety refactor in §7 already
having routed every consumer through a named helper instead of a raw
dict-access pattern, which made the actual change far more contained
than it would have been earlier.

**Two real bugs surfaced while doing the reshape, both worth knowing
about for any future coordinator shape change:**

1. **A helper that happens to work for two different things today can
   silently break for one of them once its contract changes.**
   `_fast_env()` was, before this reshape, also being used (correctly,
   at the time) to read `DockhandUpdateCoordinator.data` in two places —
   a *different*, never-reshaped coordinator whose data happened to
   share the fast coordinator's old flat shape. Once `_fast_env()` was
   updated to expect the new wrapper, those two call sites kept
   compiling and kept running — they just silently returned empty data
   instead of the real thing, since `update_coordinator.data` was never
   wrapped and never will be (it holds one kind of data, no `schedules`-
   style second concern to make room for). A test caught it via a
   `KeyError` where data should have been preserved; nothing in the type
   system or a lint pass would have. When changing what a shared helper
   assumes about its input shape, grep every call site's actual
   variable, not just its name — `self.data` reads the same whether
   `self` is the coordinator you're thinking of or a different one.

2. **Fixing a raw access pattern at its assignment point, then also
   fixing every downstream call individually, double-fixes it.** Several
   files had a local `fast_data = (coordinator.data or {}).get(
   "environments") or {}` line (the correct, one-time unwrap) followed
   later by `_fast_env(fast_data, env_id)` — unwrapping `"environments"`
   a second time from something that no longer has that key, silently
   returning empty every time. This doesn't raise; it just quietly
   returns nothing, which is the more dangerous failure mode of the two.
   When a shape changes, decide *once* where the unwrap happens for a
   given local variable — either at its assignment or at each read, not
   both — and grep specifically for the helper being called on an
   already-processed variable, not just for the raw coordinator
   reference.

3. **An earlier design decision — keeping `_fast_env`/`_slow_env`
   separate so each name would document which coordinator a call site
   expected — didn't survive contact with how the codebase had actually
   evolved.** By the time this was reconsidered, a meaningful fraction of
   call sites had already stopped calling either function in favor of a
   locally-unwrapped variable (bug 2 above is exactly how that happened),
   which undermined the "the name is documentation" argument: it can't
   be documenting anything at a call site that isn't calling it. Once
   `DockhandUpdateCoordinator` also gained the same shape, there was
   nothing left for two functions to distinguish at all. Worth revisiting
   a "these should stay separate for clarity" call if the number of call
   sites actually using the named functions (versus routing around them)
   drops — that's a sign the reasoning has stopped matching the code, not
   a reason to defend the original design harder.

4. **A reshape's ripple effects need checking against every consumer,
   not just the ones with existing tests to catch mistakes.**
   `diagnostics.py`'s `update_summary` computation iterated
   `update.data`'s top level directly — correct when that was
   `{env_id: {...}}`, silently wrong once the update coordinator's
   reshape (this same section, above) wrapped it in `"environments"`:
   it started iterating a single bogus `"environments"` key instead of
   real per-environment data. This shipped and passed the full test
   suite for several rounds of changes after the reshape, because this
   specific computation had zero test coverage — the existing
   diagnostics tests never configured a real update coordinator, so
   nothing ever exercised that code path. Found only when reviewing the
   file for an unrelated inconsistency and reading it closely enough to
   notice what it was actually iterating. A green test suite after a
   reshape means every *tested* consumer still works — it says nothing
   about untested ones. Worth deliberately grep'ing for every read of a
   reshaped coordinator's `.data` after a change like this, not just
   trusting that existing tests would have caught a break.
