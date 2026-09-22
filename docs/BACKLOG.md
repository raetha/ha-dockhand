# Backlog / considered-but-not-built

Ideas that came up during development, were deliberately evaluated, and
either deferred or rejected. Kept here so they aren't re-litigated from
scratch in a future session — if you're considering one of these, read
the reasoning first and only revisit if the stated condition has changed.

## Deferred

- **Inline release-notes body content (not just a link) for floating-tag
  images with no Dockhand `newerVersion` suggestion** — e.g. AudiobookShelf
  (`ghcr.io/advplyr/audiobookshelf:latest`) shows a "View release notes"
  link (via `_pending_update_changelog_section()`'s empty-`versions` call)
  but not the "What's Changed" body content Authentik gets when Dockhand's
  semver engine finds a concrete `newerVersion` target. Root cause is
  structural, not a bug: Dockhand's `checkNewerVersion()` explicitly skips
  floating tags ("Floating tag -> nothing to compare, and we skip the
  registry call entirely", `semver/check.ts`), so it never produces a
  target tag for these images, and `version-notes` can only fetch notes
  for tags it's given by name — there's no "everything newer than X" call
  on Dockhand's side. `resolveAndFetchReleaseNotes`'s wanted-list matching
  is also why the empty-`versions` call deliberately returns `notes: []`
  (short-circuits before any network call) even for a confident source.
  The fix would be a client-side release fetch: use the `source`/
  `changelogUrl` Dockhand's empty-`versions` call already resolves for us
  (confident sources only — GitHub or Gitea/Forgejo) to hit that forge's
  releases API ourselves, filter to releases newer than the container's
  OCI `image.version` label, and render their bodies the same way
  `_semver_advisory_section()` does.
  **Scope this narrowly if it's ever built**: only do the "everything
  newer than installed" fetch when the container's raw image tag has NO
  digits at all (`latest`, `stable`, `edge`, `nightly`, `main`, and
  similar) — a tag with any digit in it (`v3`, `16-alpine`, a partial
  CalVer pin like `2026.2`) still imposes a ceiling Install can never
  cross (Traefik's `v3` will never become `v4` via Install), and correctly
  bounding "newer than X" to that ceiling means reimplementing Dockhand's
  own flavor/major-bump constraint logic (`tag-parser.ts`) ourselves —
  real duplicated complexity, and exactly the kind of "displayed content
  doesn't match what Install can deliver" mismatch this integration has
  gone out of its way to avoid elsewhere (see the hasUpdate-vs-newerVersion
  precedence in `update.py`'s module docstring). Confirmed with the
  maintainer directly (a real example: an Authentik container with both an
  actionable same-tag update AND a newerVersion suggestion requiring
  re-pinning) that showing inline notes for anything beyond a genuinely
  ceiling-free tag is not acceptable.
  Also worth weighing before building: unauthenticated GitHub is 60
  req/hour, shared across every zero-digit-tag container a user checks
  release notes for in a session — Dockhand's own server-side fetch has
  the same limit but at least centralizes it per-Dockhand-instance rather
  than per-HA-instance.
  Deliberately not built for the 1.10.0 release — maintainer wants to see
  whether Dockhand's own semver/release-notes feature grows to cover this
  (e.g. extending `newerVersion` detection to floating tags, or a
  "since version X" mode on `version-notes`) before duplicating any of
  that logic client-side. Revisit after a few more Dockhand releases, or
  sooner if Dockhand ships something that makes this moot or easier.

- **Auto-applying a semver "newer version tag" suggestion** (i.e. having
  Install move a container to the tag `newerVersion` recommends, or editing
  the pinned tag in the container's compose file/config on the user's
  behalf). Rejected outright, not just deferred — Dockhand's own frontend
  treats this purely as an advisory, session-only badge with no install
  action (confirmed by reading `VersionUpdateModal.svelte`: a "view
  releases" link and a Close button, nothing else), and for good reason:
  the compose file is the user's own, and this integration doesn't own it.
  Editing it out from under the user, or silently changing what tag a
  freestanding container is configured with, is a correctness/trust
  problem, not a convenience — see `update.py`'s
  `_semver_advisory_only()`/module docstring for how the update entity
  reflects this (Install withheld when this is the only signal). Not
  worth revisiting unless Dockhand itself ships a "move to this tag"
  action we could call instead of reimplementing our own.

- **Re-checking a container right after Install so a "newer version tag"
  suggestion reappears immediately.** When a pinned image has both an
  installable same-tag update and a `newerVersion` suggestion, applying the
  update makes Dockhand delete that container's `pending_container_updates`
  row (`removePendingContainerUpdate()` in `batch-update-stream`), taking the
  suggestion with it. With `enable_precise_updates` on, our post-install Tier
  2 refresh brings it back right away; with it off, the entity reads as up to
  date until Dockhand's next scheduled check or a manual "Check for updates"
  press. The only way to close that gap today is an environment-wide
  `check-updates` POST after every Install — Dockhand has no single-container
  check endpoint (confirmed against Dockhand's `src/routes/api/containers/`,
  1.0.49-dev). Deferred by the maintainer during 1.10.1: a registry check of
  every container in the environment on every single update is too much load
  for the value. Revisit if Dockhand adds a per-container update check.

- **Proper destination-level device grouping for `repo_prune`/`repo_check`/
  `repo_verify` schedule types.** Discovered during the 1.9.0 Schedules
  device-hierarchy work by reading Dockhand's actual `/api/schedules` source
  (`Finsys/dockhand`, currently 1.0.39 — two patch releases ahead of the
  1.0.37 this integration was last fully reviewed against). These are backup
  *destination*-scoped maintenance jobs (prune/check/verify policies on a
  configured backup destination), not environment-scoped and not truly
  "system" either (`isSystem: false`, but `environmentId: null` — a third
  bucket distinct from both env-scoped schedules and genuine system jobs
  like `system_cleanup`). Not yet seen in a live Dockhand instance (no
  backup destinations configured at review time), so unconfirmed whether
  they're commonly used. For 1.9.0 they're handled safely but generically —
  `environmentId: null` routes them to the flat `schedules_hub` alongside
  real system jobs, same as before this rework, just without a dedicated
  "Destinations" grouping of their own. Revisit if/when backup destinations
  with these policies show up in practice and a dedicated group device
  (`_destination_group_device`, parented directly under the hub rather than
  an environment) seems worth the added complexity. The `backup` schedule
  type (destination-linked but genuinely environment-scoped via
  `config.environmentId`) is unaffected — it already groups correctly under
  its owning environment's Schedules group like any other env-scoped
  schedule.

- **Group `enable_update_entities`/`enable_precise_updates`/`poll_interval_updates`
  visually via HA's `section()` helper in the Configure form.** Tried twice in the
  unreleased 1.8.1 dev cycle (once with the three fields' `strings.json` labels
  nested under the section's own key, once flat at the top level) — both times the
  section's own header (name/description) rendered correctly, but the fields
  *inside* it showed as raw snake_case config keys with no label or help text in a
  live HA instance. The actual cause was never confirmed: frontend-source research
  strongly suggested the flat structure should be right, but it wasn't, and there's
  no way to render/verify HA's actual frontend from this environment. Reverted
  rather than keep fighting it blind — `_options_schema()` is back to fully flat
  fields, `DockhandConfigFlow.VERSION` back to 2 (the brief 2 -> 3 migration for
  this was deleted outright; nothing ever shipped at version 3). Revisit only with
  a way to actually verify rendering — e.g. a confirmed-working real HA integration
  using `section()` to copy the exact translation structure from, or some way to
  render/test the actual frontend rather than guessing from source reading.

- **Deprecate `DockhandUpdateCoordinator` (Tier 2 / `CONF_ENABLE_PRECISE_UPDATES`)
  in a future major release.** After the 1.10.0 update-entity rework, Tier 1
  (the always-on `pending-updates` poll) already carries `hasImageUpdate`/
  `newerVersion` sourced from a real registry digest check — Dockhand's own
  scheduled job (`env-update-check.ts`) computes that via the same
  `checkImageUpdateAvailable()` call Tier 2's interactive `check-updates` POST
  uses, just on Dockhand's own cron instead of ours. So Tier 2 no longer adds
  a new "is there an update" signal for ordinary containers — confirmed by
  reading both `env-update-check.ts` and `check-updates/+server.ts` directly,
  not assumed.
  **However, do not remove Tier 2 without solving this first:** Dockhand
  deliberately never persists a `pending_container_updates` row for a system
  container (Hawser, Dockhand itself) — both `env-update-check.ts`
  (`if (isSystemContainer(imageName)) continue`) and the interactive
  check-updates route (`if (result.systemContainer || result.updateDisabled)
  continue`) skip writing that row, since Dockhand's own UI intentionally
  hides system-container updates from the normal container-update flow. This
  means Tier 1's `pending-updates` cache can **never** carry update status
  for Hawser/Dockhand's own update entities, no matter how it's polled or
  improved — that data simply doesn't exist server-side outside the raw,
  unpersisted POST response. Tier 2's `DockhandUpdateCoordinator` captures
  that raw response in memory (indexed by container ID, no system-container
  filter applied client-side), which is the *only* reason our Hawser/Dockhand
  update entities can ever show "update available" today. Confirmed live:
  disabling `enable_precise_updates` makes those two entities permanently
  read as up to date, even when an update genuinely exists.
  Real remaining value of Tier 2, in order: (1) system-container update
  detection above — a hard blocker on removal as things stand; (2) a
  registry check on our own configurable cadence rather than Dockhand's
  per-environment schedule; (3) the real short digest string for display,
  which the maintainer has said isn't valuable on its own. The manual
  "Check for updates" button stays regardless of this coordinator's fate —
  it's independently useful and not the thing being reconsidered here.
  Revisit if/when Dockhand adds a way to read system-container update status
  from a cached/persisted endpoint (so Tier 1 could pick it up directly), or
  if the maintainer decides losing accurate Hawser/Dockhand update entities
  is an acceptable trade for removing the option.

- **`async_get_device_by_identifier` / `async_get_device` migration
  (target: 2.0.0, Major — raises HA floor to 2026.8.0).** HA 2026.8
  deprecated `dr.async_get(hass).async_get_device(identifiers=...)` in
  favour of two new scoped lookups (announced at
  https://developers.home-assistant.io/blog/2026/07/21/device-registry-single-config-entry/).
  The integration is deliberately staying on the old API for 1.x so the
  HA minimum stays at 2026.3.0, but the old API is marked
  `breaks_in_ha_version="2027.8.0"` — so the migration **must** land
  before 2.0.0 ships. Per SEMVER.md, raising the HA floor is a Major
  change, and per the floor rule, `ha-dockhand-cards` minimum must be
  raised to match in the same release.

  **Full implementation plan (do not reinvent):**

  1. **`helpers.py` — `_device_entry_id` function.** Change the
     2-argument signature `(hass, identifier)` to 3 arguments
     `(hass, identifier, config_entry_id)` and swap the lookup:

     ```python
     # Before (1.x — deprecated):
     device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, identifier)})

     # After (2.0.0 — HA 2026.8+):
     device = dr.async_get(hass).async_get_device_by_identifier(
         (DOMAIN, identifier), config_entry_id
     )
     ```

     `async_get_device_by_identifier` is O(1) (keyed by `(identifier,
     config_entry_id)`) and scoped to the config entry, which is
     semantically correct since every device this integration registers
     belongs to exactly one config entry.

  2. **All 9 call sites in `helpers.py`** — add `entry_id` (or the
     relevant `config_entry_id`/`entry.entry_id`) as the third argument.
     The nine sites are:

     - `_device_entry_id(hass, _device_id_env(entry_id, env_id))` — 6
       occurrences → `_device_entry_id(hass, _device_id_env(entry_id, env_id), entry_id)`
     - `_device_entry_id(hass, _device_id_stacks_group(entry_id, env_id))` — 1
       occurrence → `..., entry_id)`
     - `_device_entry_id(hass, parent_identifier)` — 2 occurrences →
       `_device_entry_id(hass, parent_identifier, entry_id)` (the
       `entry_id` is already in scope at both call sites)

  3. **`tests/test_helpers.py` — `mock_dr` fixture.** Swap the mocked
     method from `async_get_device` to `async_get_device_by_identifier`.
     The new API takes a positional `(DOMAIN, identifier)` tuple and a
     positional `config_entry_id` string (no keyword args); adjust the
     fixture's inner function accordingly:

     ```python
     def _async_get_device_by_identifier(identifier_tuple, _config_entry_id=None):
         key = identifier_tuple[1]          # second element of (DOMAIN, key)
         if key in registry_map:
             dev = MagicMock()
             dev.id = registry_map[key]
             return dev
         return None

     mock_reg.async_get_device_by_identifier = _async_get_device_by_identifier
     ```

  4. **`hacs.json`** — bump `"homeassistant"` from `"2026.3.0"` to
     `"2026.8.0"`.

  5. **`manifest.json`** — no change needed (no explicit HA version
     floor declared there).

  6. **Version bump** — `manifest.json` `"version"` from `1.9.x` to
     `"2.0.0"`. Also update `CHANGELOG.md`.

  7. **`ha-dockhand-cards`** — per SEMVER.md floor rule, update its
     minimum HA version to 2026.8.0 in the same release.

  8. **`UnitOfRatio.PERCENTAGE`** (see item below) — can be bundled
     into 2.0.0 at the same time, since that item also requires the HA
     minimum to be bumped past 2026.7.

  *Why not `async_get_devices` (plural)?* That API was also introduced
  in HA 2026.8 and returns a *list* of matching devices across all config
  entries. The singular `async_get_device_by_identifier` is the right
  choice: scoped to one config entry, single return value, O(1), and an
  exact semantic match for "find the one device this config entry
  registered under this identifier."

- **`UnitOfRatio.PERCENTAGE` for percentage sensors.** A newer HA enum
  than what this integration currently targets — requires HA minimum
  bumped past 2026.7. Current minimum is 2026.3; no other reason to bump
  it has come up yet. Bundle into the 2.0.0 release (see above) once the
  HA minimum moves for the `async_get_device_by_identifier` migration.

- **Runtime controls: Block I/O (`Blkio*`) fields.** Left out of the
  first pass — low value for home-lab use, and real complexity (per-device
  weight maps, not scalars like the other runtime controls). See
  `docs/UPDATE_RUNTIME_DESIGN.md` for the full design rationale.

- **`/api/system?env=X` for richer host/Docker info.** Returns
  `docker{version,apiVersion,os,arch,kernelVersion,serverVersion,connection}`,
  `host{}` (from Docker's own `/info`, not Node `os.*`), `runtime{}`
  (Dockhand's own process info), `database{}`, and `stats{}` — deliberately
  do **not** use `stats`, `/api/dashboard/stats` is more complete. Most of
  this overlaps what `/api/host` already gives us (platform, arch, Docker
  version). The two genuinely new fields (`apiVersion`, `kernelVersion`)
  aren't available anywhere else, but the endpoint is heavy server-side —
  it also fetches full container/image/volume/network lists just to
  compute `stats` we'd ignore — and can't replace `/api/host` (missing
  `hawserVersion`, `uptime`), so using it would be a net-new API call just
  for those two fields. Revisit if Dockhand ever adds a lighter-weight
  version of this endpoint, or if it becomes more/less inclusive.

- **Our own bulk-update button, separate from what already exists.**
  Already built as an env-level "Update all" button (see CHANGELOG) using
  `batch-update-stream`'s existing multi-container-ID support. Confirmed
  HA 2026.7's own "Update All" UI feature is frontend-only (its own
  changelog and developer docs show no bulk-install hook exposed to the
  Update entity platform) — it just calls `update.install` on each
  selected entity individually, so there was never a way to detect or
  hook into it from an integration. Nothing further to do here unless HA
  core adds a real bulk-install primitive later.

- **Slow coordinator's per-environment gather** (`return_exceptions=True`,
  logs and omits that env's key from `environments` this cycle on
  failure) — checked against the fetch-failure principle in
  `docs/ARCHITECTURE.md` §3 and not currently believed to be the same
  bug (a missing dict key reads as "no fresh data this cycle" to
  consumers going through `_coordinator_env`, not "confirmed
  empty"), but wasn't traced all the way through every
  slow-coordinator-driven cleanup path (images/volumes/networks) the
  way the fast coordinator was. Worth a closer look if a similar
  disappearing-devices report ever surfaces for those entity types
  specifically.

## Rejected

- **Activity stats `byAction` breakdown as a separate sensor.** Tried and
  reverted during 1.8.0 development as a pure duplicate — the existing
  `DockhandEnvActivityEventsSensor` already has `today`/`total`; `byAction`
  (from `GET /api/activity/stats`) could be added as an *attribute* on
  that existing sensor if wanted later, but does not warrant new entities.

- **Config-sets** (Dockhand's reusable env-var/label bundles for stack
  deploys). Reviewed and deliberately not implemented — no live state,
  pure deploy-time template metadata, nothing maps to an HA entity
  concept.

- **Two-tier "gentle Deploy / forceful Update" buttons, symmetric across
  internal and git stacks.** Not achievable — see
  `docs/ARCHITECTURE.md` §6 for why (no per-call pull override exists
  for git stacks at all). Went with one Deploy/Redeploy button per stack
  type instead, each mirroring Dockhand's own default UI behavior as
  closely as possible for that type.

- **Stack/container/image/volume/network `configuration_url`s stay pointed
  at the generic list pages** (`/stacks`, `/containers`, `/images`, etc.),
  not deep-linked to a specific item, unlike the environment device's
  settings link (which does deep-link, per `dashboard-header.svelte`'s
  `goto` call). Checked: these pages do support a `?search=<name>` query
  param that filters the list client-side, but there's no URL-level
  environment-scoping anywhere in Dockhand's frontend (`$currentEnvironment`
  is a plain client-side store, never synced to/from the URL) — a
  `?search=` link would silently show wrong or empty results if the
  environment currently selected in Dockhand's own UI doesn't match the
  one the link was generated for. Not worth the confusion for an
  imprecise deep link; revisit if Dockhand ever adds env-scoped URLs.
