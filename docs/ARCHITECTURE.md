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

## 3. Coordinator architecture

- `DockhandFastCoordinator` (60s): dashboard stats, containers, stacks,
  container resource stats, pending-update flags. This is also the sole
  source of which environments exist — no coordinator calls
  `/api/environments` for enumeration (see below).
- `DockhandSlowCoordinator` (600s): images, volumes, networks, schedules,
  runtime controls, git stacks, host info, auto-update settings, and
  env_meta (see below). Derives its own environment-id list from the fast
  coordinator's already-fetched data (fast completes its first refresh
  before slow starts, per `__init__.py`'s setup order) rather than
  making a call of its own.
- `DockhandUpdateCoordinator` (24h default, optional): only created when
  `CONF_ENABLE_PRECISE_UPDATES` is on. Purely additive — see below.

**`/api/environments` is never used for environment enumeration**, and
its raw response is never stored. It returns Dockhand's own secrets
(`tlsKey`, `hawserToken`) fully decrypted with no redaction on Dockhand's
side, so which environments exist is sourced instead from
`/api/dashboard/stats` (id/name/icon/connectionType/online/labels/
updateCheckEnabled) — that's what both coordinators actually enumerate
from. It's used for the one-time connectivity probe during config flow
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
on the *same* entities — it never gates entity creation or removal. If you
build another feature with this "free basic signal, paid precise signal"
shape, follow this same structure: cheap tier owns entity lifecycle,
expensive tier is a pure data enrichment layered on top.

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
a new approach. (The 1.2.0 session-cookie removal used a different,
force-reauth-inline approach because that migration genuinely required
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
