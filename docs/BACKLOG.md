# Backlog / considered-but-not-built

Ideas that came up during development, were deliberately evaluated, and
either deferred or rejected. Kept here so they aren't re-litigated from
scratch in a future session — if you're considering one of these, read
the reasoning first and only revisit if the stated condition has changed.

## Deferred

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
