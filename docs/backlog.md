# Backlog / considered-but-not-built

Ideas that came up during development, were deliberately evaluated, and
either deferred or rejected. Kept here so they aren't re-litigated from
scratch in a future session — if you're considering one of these, read
the reasoning first and only revisit if the stated condition has changed.

## Deferred

- **Drop the pre-2026.10 typing workarounds once the minimum Home Assistant
  version reaches 2026.10.** That release switched form schemas to probatio
  (aliasing `import voluptuous` to it at runtime) and moved
  `BinarySensorDeviceClass` to `homeassistant.components.binary_sensor.const`.
  The minimum (2026.3) has neither, so `config_flow.py` keeps voluptuous and
  passes schemas through `_form()`, and `binary_sensor.py`'s import carries a
  `type: ignore`. At 2026.10+: build the schemas with probatio directly,
  delete `_form()`, and import from `binary_sensor.const`. Likewise
  `number.py`'s `async_entity_id_changed` ignore once the minimum reaches
  2026.11 (where it becomes an ordinary `@override`). See
  `docs/quality-scale.md`.

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

- **Group `enable_update_entities`/`enable_precise_updates`/`poll_interval_precise_updates`
  visually via HA's `section()` helper in the Configure form.** Tried twice in the
  unreleased 1.8.1 dev cycle (once with the three fields' `strings.json` labels
  nested under the section's own key, once flat at the top level) — both times the
  section's own header (name/description) rendered correctly, but the fields
  *inside* it showed as raw snake_case config keys with no label or help text in a
  live HA instance. The actual cause was never confirmed: frontend-source research
  strongly suggested the flat structure should be right, but it wasn't, and there's
  no way to render/verify HA's actual frontend from this environment. Reverted
  rather than keep fighting it blind — `_options_schema()` is back to fully flat
  fields, and its brief config entry migration was deleted outright (nothing
  shipped with it; 1.11.0's schema 2.2 is an unrelated, real rename). Revisit only with
  a way to actually verify rendering — e.g. a confirmed-working real HA integration
  using `section()` to copy the exact translation structure from, or some way to
  render/test the actual frontend rather than guessing from source reading.

- **Container and stack tags** (Dockhand 1.0.49+). Dockhand now has
  user-defined tags with a name, colour and icon (`GET /api/tags`), assigned
  per container (`GET /api/container-tags?env=` → `{name: [tagId]}`) and per
  stack (`GET /api/stack-tags?env=`), plus a `dockhand.tags` container label
  that stacks inherit. Exposing them would mean a `tags` attribute (names,
  maybe colours) on the container and stack state/status sensors, fetched
  per environment on the slow coordinator (needs `containers:view` /
  `stacks:view`). The main consumer would be ha-dockhand-cards: tag pills
  and filtering/grouping by tag, which fits the filters planned for cards
  2.0.0. Raetha: worth doing, not urgent (2026-10-14).

- **`UnitOfRatio.PERCENTAGE` for percentage sensors.** A newer HA enum
  than what this integration currently targets — requires HA minimum
  bumped past 2026.7. Current minimum is 2026.3; no other reason to bump
  it has come up yet (the `async_get_device_by_identifier` migration that
  was expected to force it landed in 1.11.0 behind feature detection
  instead, keeping the minimum where it is).

- **Runtime controls: Block I/O (`Blkio*`) fields.** Left out of the
  first pass — low value for home-lab use, and real complexity (per-device
  weight maps, not scalars like the other runtime controls). See
  `docs/update-runtime-design.md` for the full design rationale.

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
  `docs/architecture.md` §3 and not currently believed to be the same
  bug (a missing dict key reads as "no fresh data this cycle" to
  consumers going through `_coordinator_env`, not "confirmed
  empty"), but wasn't traced all the way through every
  slow-coordinator-driven cleanup path (images/volumes/networks) the
  way the fast coordinator was. Worth a closer look if a similar
  disappearing-devices report ever surfaces for those entity types
  specifically.

## Rejected

- **Removing precise updates (`DockhandUpdateCoordinator`, Tier 2 /
  `CONF_ENABLE_PRECISE_UPDATES`).** Kept on purpose (Raetha, 2026-10-15): it's
  the only way to see that a system container (Dockhand itself, a Hawser
  agent) has an update. Dockhand never persists a `pending_container_updates`
  row for a system container — both `env-update-check.ts`
  (`if (isSystemContainer(imageName)) continue`) and the check-updates route
  skip writing it — so the always-on Tier 1 `pending-updates` poll can never
  report one; only Tier 2's in-memory copy of the raw check-updates response
  does (confirmed live: with precise updates off, those entities always read
  as up to date). For ordinary containers Tier 2 adds no new signal since
  1.10.0 — Tier 1 carries the same registry result from Dockhand's own
  scheduled check. Revisit only if Dockhand starts exposing system-container
  update status through a stored, pollable endpoint. Precise updates also
  drives the self-update check that reports a newer release for a
  version-pinned Dockhand (#48).

- **Running a command inside a container from HA** (Dockhand 1.0.49+'s
  `POST /api/containers/{id}/exec/run`, which runs a short command and
  returns stdout, stderr and the exit code). Too powerful to trigger from
  HA directly for now — anything that can call an HA action could run
  arbitrary commands in any container. Only worth revisiting as part of a
  deliberate, opt-in "advanced features" set (off by default, clearly
  warned, ideally admin-only), never as an ordinary entity or action
  (Raetha, 2026-10-14).

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
  `docs/architecture.md` §6 for why (no per-call pull override exists
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
