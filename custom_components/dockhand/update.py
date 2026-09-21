"""Update platform for Dockhand container image updates.

Whole platform gated on CONF_ENABLE_UPDATE_ENTITIES (default True, for
upgrade compatibility — Tier 1 was unconditional before this option
existed). Off entirely disables both tiers' ENTITIES below, and the
env-level bulk "Update all" button (button.py/__init__.py) since it has
nothing to act on without them — that's the actual "backdoor to
performing updates from HA" concern behind this option. It does NOT
disable the update_coordinator (Tier 2) object itself or the env-level
"Check for updates" button: that button is read-only (forces a real
registry check, refreshing Dockhand's own cached values that other
things — e.g. the stack binary sensor's pending-updates attributes —
still consume regardless of whether update entities exist), so it keeps
working whenever CONF_ENABLE_PRECISE_UPDATES is on, independent of this
toggle. See __init__.py's update_coordinator construction for that
split. Added in response to github.com/raetha/ha-dockhand/issues/23 —
some users manage container updates outside HA entirely and don't want
these entities cluttering HA's own update management.

Two-tier design for entity DISPLAY (both tiers require
CONF_ENABLE_UPDATE_ENTITIES to be on — Tier 2 alone, e.g. via a manual
"Check for updates" press with entities disabled, has nothing to show
its data on):

  Tier 1 (no separate config option beyond the platform gate above):
  update entities exist for every container in any environment where
  Dockhand itself has update-check enabled
  (env_data["stats"]["updateCheckEnabled"], from dashboard/stats,
  already polled by the fast coordinator — no separate check needed).
  installed_version shows the image tag (no digest available at this
  tier). latest_version flips to the "update-pending" sentinel — or, once
  bug #2 below shipped, the container's own raw image tag when that's
  distinguishable from installed_version — when the fast coordinator's
  cheap GET /api/containers/pending-updates poll (Dockhand's own cached
  scheduled-check results, no registry query of its own) flags this
  container. That same poll (DockhandFastCoordinator, see its own
  docstring) also carries hasImageUpdate/newerVersion per container —
  confirmed richer than originally assumed — so Tier 1 alone is now a
  full source of "is there an update" and "is there a semver suggestion",
  not just a boolean flag. Install works fully at this tier —
  POST /api/containers/batch-update-stream only needs a container ID,
  never a digest.

  Tier 2 (CONF_ENABLE_PRECISE_UPDATES, purely additive): also runs
  DockhandUpdateCoordinator, a real (deliberately infrequent, default
  24h) POST /api/containers/check-updates registry query per environment.
  When present, its data layers precise digest-based installed_version/
  latest_version onto the *same* entities Tier 1 already created — it
  does not create separate entities.

  _check_updates_item() is what merges the two: Tier 2's item for this
  container (hasUpdate, digests, newerVersion) when Tier 2 has one,
  falling back to Tier 1's pending_update_details entry
  (hasImageUpdate/newerVersion) entirely whenever Tier 2 has no row for
  this container at all (Tier 2 disabled, or Tier 2 ran but excluded/
  hasn't reached this container). Tier 2's own newerVersion still wins
  when it has one; Tier 1's fills the gap only when Tier 2's doesn't
  carry one. This used to return {} outright whenever Tier 2 was absent
  or had no row, discarding Tier 1's data completely — the root cause of
  both bugs below.

The "Install" button triggers a pull-and-recreate via
POST /api/containers/batch-update-stream, which (unlike the older
batch-update endpoint) runs vulnerability scanning when a scanner is
configured on the environment, and blocks the update per the environment's
configured vulnerabilityCriteria. Progress is reported via
update_percentage, derived from polling GET /api/jobs/{id}.

Version string strategy:
  installed_version — Preferred: the running container's
                      org.opencontainers.image.version label (e.g.
                      "v3.1.0"), when the image author set one — see
                      helpers._image_version_label. Falls back to Tier 2's
                      first 12 hex chars of the sha256 from currentDigest
                      ("image@sha256:<hex>") when no such label exists.
                      Final fallback (no label, no Tier 2 data yet): the
                      container's image tag.
  latest_version    — Preferred: the merged item's hasUpdate=True (first
                      12 hex chars of newDigest, "sha256:<hex>", no image
                      prefix, when Tier 2 supplied a real digest) — a
                      real, actionable digest-level update on the
                      container's OWN pinned tag always wins, even when a
                      semver newerVersion suggestion is also present (see
                      below for why). hasUpdate=True with NO digest — the
                      common case whenever this signal came from Tier 1's
                      own hasImageUpdate rather than a Tier 2 digest
                      check — falls back to the container's raw image tag
                      (distinguishable from installed_version whenever
                      installed_version is an OCI-label-derived version
                      string), or the "update-pending" sentinel only when
                      the raw tag would collide with installed_version
                      (no OCI label was found, so installed_version
                      already IS just the tag). Falling all the way back
                      to plain installed_version in this no-digest case
                      used to make the entity read as falsely "up to
                      date" (HA renders STATE_OFF whenever latest_version
                      == installed_version) — see bug #2 this fixed.
                      Otherwise, Dockhand's own opt-in semver "newer
                      version tag" detection (1.0.43+, global setting),
                      when the merged item carries a newerVersion field
                      for this container — a real target tag (e.g.
                      "16.4-alpine"), not a digest. Otherwise, Tier 1's
                      own pending-updates cache flag (independent of the
                      merged item — see _pending_via_dockhand_cache()):
                      "update-pending" (deliberately not a real
                      digest/version string). Otherwise: same as
                      installed_version.

Why hasUpdate beats newerVersion, not the other way round: newerVersion
always targets the HIGHEST version tag it finds, not the immediate next
one — e.g. a container pinned to "1.2" (which tracks its own patch
releases) with both "1.2.3" and "1.3.0" published would get newerVersion
targeting "1.3.0", with "1.2.3" listed only in its own `skipped` array.
But "1.2.3" is what a same-tag digest change (hasUpdate=True) would
actually deliver via Install — "1.3.0" needs the pinned tag itself
changed, which Install can't do (see below). Showing "1.3.0" as
latest_version while Install lands on "1.2.3" would make the displayed
target and Install's real effect disagree. Deferring the newerVersion
suggestion until hasUpdate resolves to False also gives the natural
behavior of one actionable step at a time: install the "1.2.3" patch,
then "1.3.0" (if still the newest available) surfaces as the next,
advisory-only, suggestion.

Semver "newer version tag" detection is advisory only — confirmed against
Dockhand's own frontend (routes/containers/+page.svelte's
"newerVersions" store and VersionUpdateModal.svelte, which has no install
action, only a "view releases" link). The container stays pinned to its
current tag; a newerVersion suggestion never means Install would actually
pull that tag — Install always re-pulls whatever the container is
currently configured with. _update_supported_features() below withholds
UpdateEntityFeature.INSTALL specifically for the case where newerVersion
is the ONLY reason installed_version != latest_version (hasUpdate=False),
since offering it there would look like a working button that silently
does nothing. async_release_notes()'s semver advisory section is itself
only shown when hasUpdate is False (see _newer_version_section() /
_semver_advisory_section()) — the same gating as latest_version above,
for the same reason — and states the advisory caveat plainly whenever it
does appear.

When there's a pending/actionable update but NO newerVersion suggestion
to go with it (the common Tier-1-only case, or Tier 2 on but without a
newerVersion for this container), _newer_version_section() instead calls
_pending_update_changelog_section(), which asks Dockhand's version-notes
endpoint for a bare changelog link with an empty `versions` list — this
is the fix for bug #1 (release notes/changelog links disappearing
entirely whenever there was no specific semver target to attach them
to). See api.py's async_get_version_notes docstring for exactly how
Dockhand resolves this with no wanted versions.

Release notes for a newerVersion suggestion, or a bare changelog link
for a plain pending update, both come from Dockhand's own
GET /api/containers/{id}/version-notes (1.0.43+, same feature the semver
version detection is part of) via client.async_get_version_notes() —
Dockhand does the forge resolution (GitHub or self-hosted Gitea/Forgejo)
and release-matching itself, including its own unauthenticated-GitHub
rate-limit handling. Deliberately not reimplemented client-side here.

systemContainer/updateDisabled (whether Install is offered at all) used
to only be known via check-updates. systemContainer is Dockhand's own
precomputed field on the regular containers list already (GET
/api/containers) — the same isSystemContainer(imageName) classification
Dockhand's UI itself uses, image-name matching we don't need to
replicate and can't get out of sync with (if Dockhand adds a new system
container type, this field reflects it automatically). updateDisabled
has no such precomputed field on that endpoint, so it's still computed
client-side from the `dockhand.update` label — see
helpers._is_update_disabled_by_label, kept in sync with Dockhand's own
matching logic. Both work identically whether or not Tier 2 is enabled.
"""

import asyncio
import logging
from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DockhandConfigEntry
from .const import CONF_ENABLE_UPDATE_ENTITIES, DEFAULT_ENABLE_UPDATE_ENTITIES, DOMAIN
from .coordinator import DockhandFastCoordinator, DockhandUpdateCoordinator
from .helpers import (
    _all_envs,
    _coordinator_env,
    _find_container,
    _image_version_label,
    _is_update_disabled_by_label,
    already_registered,
)

_LOGGER = logging.getLogger(__name__)

# Updates trigger pull-and-recreate via the API — serialise to avoid concurrent
# pulls on the same host. 0 = coordinator manages updates, no HA-level limit.
PARALLEL_UPDATES = 0

# How often to poll GET /api/jobs/{id} while an install is running.
_JOB_POLL_INTERVAL_SECONDS = 2
# Upper bound on total wait — protects against a job stuck in "running"
# forever (e.g. a Dockhand-side crash mid-job). Generous because a scan
# plus a large image pull can legitimately take several minutes.
_JOB_POLL_MAX_ATTEMPTS = 900  # 900 * 2s = 30 minutes

# Dockhand's own "current"/"total" on batch-update-stream progress lines
# are a batch-index counter (current = i+1 over containerIds.length), NOT
# intra-container progress — meaningless here since we always send exactly
# one container ID, so total is always 1 and current/total hits 100% on
# the very first progress line (step="pulling"), long before the actual
# pull/scan/recreate work happens. We derive our own percentage instead,
# from the fixed, known pipeline of "step" values Dockhand's route always
# emits in this order for a single container: pulling -> scanning (only
# if a scanner is configured) -> creating -> done. Monotonically
# increasing only, in case of any out-of-order duplicate step events
# (e.g. "creating" is sent more than once via a progress callback during
# the actual recreate call).
_STEP_PERCENTAGES = {
    "pulling": 20,
    "scanning": 45,
    "creating": 75,
    "done": 100,
}

# Cap a fetched release-notes body — some upstream release bodies embed
# screenshots/large diffs. Same bound the more-info dialog's other content
# implicitly respects; this is the one piece sourced from outside Dockhand.
_RELEASE_NOTES_MAX_CHARS = 4000


def _short_digest(digest: str) -> str:
    """Return a short human-readable version string from a digest reference.

    Handles both formats returned by the API:
      currentDigest: "ghcr.io/finsys/hawser@sha256:53bb1e23fb302f..."
      newDigest:     "sha256:79f926e8d8fe31c0dfe90858f90b69bfd4cfbb..."

    Returns the first 12 hex chars of the sha256, e.g. "53bb1e23fb30".
    Falls back to the raw digest string if parsing fails.
    """
    try:
        sha_part = digest.split("sha256:")[-1]
        return sha_part[:12] if sha_part else digest
    except Exception:
        return digest


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DockhandConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up container update entities.

    Tier 1 entities are created for every container in an environment
    with updateCheckEnabled=True, sourced entirely from the fast
    coordinator — independent of whether Tier 2 (update_coordinator) is
    configured at all.

    Removal (when updateCheckEnabled turns off for an environment, a
    container disappears, or CONF_ENABLE_UPDATE_ENTITIES itself is
    turned off) is centralized in __init__.py's
    _cleanup_stale_registry/_build_live_sets, alongside every other
    conditionally-present entity type (images, networks, volumes,
    runtime controls, git stack entities) — not handled here. That
    function already distinguishes "environment confirmed online but
    this item is genuinely gone" from "poll failed / environment
    offline" (which must never trigger cleanup), so update entities
    reuse that same safety logic rather than duplicating it.
    """
    if not entry.options.get(
        CONF_ENABLE_UPDATE_ENTITIES, DEFAULT_ENABLE_UPDATE_ENTITIES
    ):
        return

    data = entry.runtime_data
    fast_coordinator = data.fast_coordinator
    update_coordinator = data.update_coordinator  # Tier 2, may be None

    known_ids = entry.runtime_data.known_entity_ids

    def _add_new_entities() -> None:
        fast_data = _all_envs(fast_coordinator.data)
        new_entities = []

        for env_id, env_data in fast_data.items():
            stats = env_data.get("stats") or {}
            if not stats.get("updateCheckEnabled"):
                continue
            env_name = stats.get("name", f"Environment {env_id}")

            for container in env_data.get("containers") or []:
                container_name = container.get("name", "")
                if not container_name:
                    continue
                entity = ContainerUpdateEntity(
                    fast_coordinator=fast_coordinator,
                    update_coordinator=update_coordinator,
                    entry_id=entry.entry_id,
                    env_id=env_id,
                    env_name=env_name,
                    container_name=container_name,
                )
                if already_registered(
                    hass,
                    known_ids,
                    "update",
                    entity.unique_id,
                    pending_readd_ids=entry.runtime_data.pending_readd_entity_ids,
                ):
                    continue
                new_entities.append(entity)

        if new_entities:
            async_add_entities(new_entities)

    # Add entities for initial data
    _add_new_entities()

    # Re-run on each fast-coordinator update to pick up new containers or
    # environments that just had update-check turned on in Dockhand.
    entry.async_on_unload(fast_coordinator.async_add_listener(_add_new_entities))


class ContainerUpdateEntity(CoordinatorEntity[DockhandFastCoordinator], UpdateEntity):
    """Update entity for a single container's image update status.

    Both identity (unique_id) and device attachment use (env_id, container_name).
    Docker enforces unique container names per host, so this is stable across
    container recreation (image updates), preserving historical entity data and
    automations.

    Primary coordinator is the fast one — Tier 1 works off it alone.
    update_coordinator (Tier 2) is optional and only consulted directly for
    richer digest data when present; it is never required for this entity
    to exist, be available, or support Install.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        fast_coordinator: DockhandFastCoordinator,
        update_coordinator: DockhandUpdateCoordinator | None,
        entry_id: str,
        env_id: int,
        env_name: str,
        container_name: str,
    ) -> None:
        super().__init__(fast_coordinator)
        self._update_coordinator = update_coordinator
        self._entry_id = entry_id
        self._env_id = env_id
        self._container_name = container_name

        self._attr_unique_id = f"{entry_id}_{env_id}_update_{container_name}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_container_{env_id}_{container_name}")},
        )

        self._update_supported_features()

    def _container(self) -> dict | None:
        return _find_container(
            self.coordinator.data, self._env_id, self._container_name
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"name": self._container_name}

    def _pending_update_detail(self) -> dict:
        """Return Tier 1's own pending_update_details entry for this
        container — {"hasImageUpdate": bool, "newerVersion": dict | None}
        — or {} if the fast coordinator has nothing for it (no Dockhand
        update-check has ever flagged or suggested anything for this
        container, or Dockhand's update-check isn't configured for this
        environment at all).

        Always available whenever Dockhand's own update-check is enabled
        for the environment, whether or not Tier 2
        (CONF_ENABLE_PRECISE_UPDATES) is configured — see
        DockhandFastCoordinator's own docstring for exactly how this is
        built from GET /api/containers/pending-updates.
        """
        c = self._container()
        if not c or not c.get("id"):
            return {}
        fast_data = _all_envs(self.coordinator.data)
        env_data = fast_data.get(self._env_id) or {}
        details = env_data.get("pending_update_details") or {}
        return details.get(c["id"]) or {}

    def _check_updates_item(self) -> dict:
        """Return this container's merged update-status payload — Tier 2's
        (check-updates) item, if update_coordinator is configured and has
        data for it, MERGED with Tier 1's pending_update_details entry
        (hasImageUpdate/newerVersion, always available whenever Dockhand's
        own update-check is enabled — independent of Tier 2).

        Precedence: Tier 2's own hasUpdate/digests are authoritative
        whenever Tier 2 has a row for this container at all (it's a live
        registry check) — Tier 1 is used only to fill in newerVersion when
        Tier 2's row doesn't carry one. When Tier 2 has NO row for this
        container — Tier 2 disabled entirely, or Tier 2 ran but returned
        nothing for it (e.g. a system container check-updates itself
        excludes, or a container Tier 2 simply hasn't reached this poll)
        — the returned item is built entirely from Tier 1's detail
        instead, so hasUpdate/newerVersion still surface without ever
        needing Tier 2. This used to return {} unconditionally whenever
        Tier 2 was absent, discarding Tier 1's own hasImageUpdate/
        newerVersion data entirely — see the module docstring's "Two-tier
        design" section and bug #1/#2 it links to.

        Looked up by the container's *current* id (from Tier 1's fresh
        container list), not by name. Tier 2's data is keyed by
        container_id at fetch time; a container recreated since Tier 2
        last ran (the normal effect of an image update) gets a new id,
        so its stale entry — still sitting under the old id — simply
        won't be found here. Previously this scanned by containerName
        instead, which meant a resolved update kept showing as pending
        for up to 24h (Tier 2's poll interval) after the container was
        actually recreated with the update already applied, since the
        name-matched stale entry doesn't know it's describing a
        container that no longer exists. Real bug, reported by Raetha.
        """
        c = self._container()
        if not c or not c.get("id"):
            return {}

        tier2_item: dict = {}
        if self._update_coordinator is not None:
            env_data = _coordinator_env(self._update_coordinator.data, self._env_id)
            tier2_item = env_data.get(c["id"]) or {}

        tier1_detail = self._pending_update_detail()

        if tier2_item:
            merged = dict(tier2_item)
            if not merged.get("newerVersion") and tier1_detail.get("newerVersion"):
                merged["newerVersion"] = tier1_detail["newerVersion"]
            return merged

        if tier1_detail:
            return {
                "hasUpdate": bool(tier1_detail.get("hasImageUpdate")),
                "newerVersion": tier1_detail.get("newerVersion"),
            }

        return {}

    def _semver_advisory_only(self, item: dict) -> bool:
        """True when a newerVersion suggestion is the ONLY signal that
        installed_version != latest_version for this container — i.e.
        hasUpdate is False (note: `item` is the already-merged
        _check_updates_item() result, so this already reflects Tier 1's
        own hasImageUpdate whenever Tier 2 has no row for this container
        — see that method's docstring) and Tier 1's own pending-cache
        doesn't flag it either. In that case Install would silently
        re-pull the container's current (still-pinned) tag rather than
        moving it to the suggested one — see the module docstring's
        "Semver 'newer version tag' detection is advisory only" section —
        so it must not be offered."""
        if item.get("hasUpdate") or self._pending_via_dockhand_cache():
            return False
        return bool((item.get("newerVersion") or {}).get("tag"))

    def _update_supported_features(self) -> None:
        c = self._container() or {}
        labels = c.get("labels") or {}
        update_disabled = _is_update_disabled_by_label(labels)
        is_system = bool(c.get("systemContainer"))
        if (
            update_disabled
            or is_system
            or self._semver_advisory_only(self._check_updates_item())
        ):
            self._attr_supported_features = UpdateEntityFeature.RELEASE_NOTES
        else:
            self._attr_supported_features = (
                UpdateEntityFeature.INSTALL
                | UpdateEntityFeature.RELEASE_NOTES
                | UpdateEntityFeature.PROGRESS
            )

    @property
    def installed_version(self) -> str | None:
        c = self._container()
        version = _image_version_label((c or {}).get("labels"))
        if version:
            # A real application version (e.g. "v3.1.0") beats a digest or
            # raw tag whenever the image author bothered to label it —
            # available from Tier 1 data alone, no Tier 2 required.
            return version
        digest = self._check_updates_item().get("currentDigest", "")
        if digest:
            return _short_digest(digest)
        # Final fallback: no label, no real digest available yet — show
        # the image tag instead, still meaningful, just not a precise
        # version.
        return (c or {}).get("image") or None

    def _pending_via_dockhand_cache(self) -> bool:
        """True if Dockhand's own (cheap, no-registry-query) pending-updates
        cache already flags this container, keyed by its current container
        ID from the fast coordinator's container list."""
        fast_data = _all_envs(self.coordinator.data)
        env_data = fast_data.get(self._env_id) or {}
        pending_ids = env_data.get("pending_update_container_ids") or set()
        if not pending_ids:
            return False
        c = self._container()
        return bool(c) and c.get("id") in pending_ids

    @property
    def latest_version(self) -> str | None:
        item = self._check_updates_item()
        if item.get("hasUpdate"):
            # A real, actionable digest-level update on the container's
            # OWN pinned tag always wins over a semver suggestion — see
            # module docstring's worked example (pinned to "1.2", both
            # "1.2.3" and "1.3.0" available at once). Showing "1.3.0" here
            # while Install would actually land on "1.2.3" would make the
            # displayed target and Install's real effect disagree.
            new_digest = item.get("newDigest", "")
            if new_digest:
                return _short_digest(new_digest)
            # No real digest attached to this hasUpdate=True signal — now
            # the COMMON case, since Tier 1's own hasImageUpdate (which
            # never carries a digest at all) can flow through here on its
            # own via _check_updates_item()'s merge, whether or not Tier 2
            # is configured. Falling back to installed_version here (the
            # old behavior) made the entity look falsely "up to date" —
            # HA renders STATE_OFF whenever latest_version ==
            # installed_version — even though there genuinely IS a
            # pending update. See module docstring, bug #2.
            #
            # Prefer the container's raw image tag instead: a real,
            # meaningful string, and distinguishable from
            # installed_version whenever installed_version came from the
            # OCI version label rather than the tag itself (e.g.
            # installed_version="1.2.17", raw tag="latest"). Only fall
            # back to the synthetic "update-pending" sentinel when the raw
            # tag is NOT distinguishable — no OCI label was found, so
            # installed_version already IS just the tag, and showing it
            # again here would collide and falsely read as up to date.
            raw_tag = (self._container() or {}).get("image") or None
            installed = self.installed_version
            if raw_tag and raw_tag != installed:
                return raw_tag
            return "update-pending"
        newer_tag = (item.get("newerVersion") or {}).get("tag")
        if newer_tag:
            # No actionable digest update right now — safe to surface the
            # semver suggestion. _update_supported_features() withholds
            # Install for this case via _semver_advisory_only(). Once the
            # container catches up to its pinned tag's latest content,
            # hasUpdate flips to False and this naturally takes over.
            return newer_tag
        if self._pending_via_dockhand_cache():
            # Deliberately not a real digest — see module docstring. This
            # is Tier 1's own signal, present whether or not Tier 2 (real
            # digest data) is configured at all.
            return "update-pending"
        return self.installed_version

    def _scanner_enabled(self) -> bool:
        """Return True if vulnerability scanning is enabled on this environment."""
        fast_data = _all_envs(self.coordinator.data)
        stats = (fast_data.get(self._env_id) or {}).get("stats") or {}
        return bool(stats.get("scannerEnabled", False))

    @property
    def release_summary(self) -> str | None:
        """Not used — release notes cover all warning content."""
        return None

    async def _newer_version_section(self, item: dict) -> str | None:
        """Pick which "what's coming" section, if any, belongs in the
        release notes dialog for this container's current merged
        update-status item — two mutually exclusive cases:

          1. A semver newerVersion suggestion (advisory only) is present
             and there's no actionable update pending right now —
             unchanged from before, delegated to
             _semver_advisory_section(). Suppressed whenever an
             actionable digest update IS pending (item.get("hasUpdate")),
             same reasoning as latest_version's own precedence: showing
             the semver target while Install is about to land on a
             different one would mix two targets in the same place; this
             reappears automatically once hasUpdate resolves to False.

          2. There IS a pending/actionable update right now (hasUpdate,
             per the merged item — which by now already reflects Tier 1's
             own hasImageUpdate whenever Tier 2 has no row for this
             container — OR Tier 1's own pending-updates cache, in the
             same divergent-Tier-2 case latest_version's own trailing
             fallback handles), but Dockhand has no newerVersion
             suggestion to go with it. This is the fix for bug #1: release
             notes/changelog links used to disappear entirely for a plain
             pending update whenever there was no semver target to attach
             them to (most commonly with Tier 2 off, or Tier 2 on but not
             yet reporting a newerVersion for this specific container).
             Delegated to _pending_update_changelog_section(), which
             calls Dockhand's version-notes endpoint with an empty
             `versions` list — resolves a bare changelogUrl for a
             "CONFIDENT" source with zero extra network calls, and
             correctly yields nothing for an unconfident source (see
             api.py's async_get_version_notes docstring).

        Neither applies (returns None) when there's no pending update at
        all and no newerVersion suggestion either — nothing to say here.
        """
        newer = item.get("newerVersion") or {}
        tag = newer.get("tag")

        if tag and not item.get("hasUpdate"):
            return await self._semver_advisory_section(tag, newer)

        has_pending = bool(item.get("hasUpdate")) or self._pending_via_dockhand_cache()
        if not tag and has_pending:
            return await self._pending_update_changelog_section()

        return None

    async def _semver_advisory_section(self, tag: str, newer: dict) -> str | None:
        """Build the semver "newer version tag" advisory section — see
        the module docstring's "Semver 'newer version tag' detection"
        section for what this is and why it's advisory only.

        Best-effort: any failure to reach Dockhand's version-notes
        endpoint just omits this section, same fail-open policy as
        _vulnerability_criteria() — a missing changelog must never break
        the dialog or Install.
        """
        c = self._container()
        container_id = (c or {}).get("id")
        if not container_id or self.hass is None:
            # self.hass is None only in unit tests that never attach the
            # entity to hass — the client's session needs it.
            return None

        versions = newer.get("skipped") or [tag]
        try:
            result = await self.coordinator.client.async_get_version_notes(
                self._env_id, container_id, versions
            )
        except Exception as err:
            _LOGGER.debug(
                "Could not fetch version notes for container '%s' (env %s): %s: %s",
                self._container_name,
                self._env_id,
                type(err).__name__,
                err,
            )
            return None

        lines = [f"A newer version tag is available: **{tag}**."]

        notes = result.get("notes") or []
        target_note = next((n for n in notes if n.get("version") == tag), None)
        if target_note and target_note.get("body"):
            body = target_note["body"].strip()
            if len(body) > _RELEASE_NOTES_MAX_CHARS:
                body = body[:_RELEASE_NOTES_MAX_CHARS].rstrip() + "\n\n… (truncated)"
            lines.append(body)

        skipped_count = len(versions) - 1
        if skipped_count > 0:
            lines.append(f"_{skipped_count} version(s) skipped along the way._")

        changelog_url = result.get("changelogUrl")
        if changelog_url:
            lines.append(f"[View full release notes]({changelog_url})")

        msg = (
            "This is advisory only — the container is pinned to its"
            " current tag, so Install will not move it to this version."
            " Update the tag in your compose file or container config to"
            " upgrade."
        )
        lines.append(f"<ha-alert alert-type='info'>{msg}</ha-alert>")

        return "\n\n".join(lines)

    async def _pending_update_changelog_section(self) -> str | None:
        """Bare changelog-link section for a pending/actionable update
        that has no semver newerVersion target to attach notes to — the
        fix for bug #1 (see _newer_version_section's own docstring).

        Calls Dockhand's version-notes endpoint with an empty `versions`
        list: no specific version to fetch notes for, but Dockhand still
        resolves and returns a bare changelogUrl whenever it can
        confidently identify the image's source (an
        org.opencontainers.image.source label pointing at GitHub/Gitea/
        Forgejo, or a ghcr.io/<owner>/<repo> image name) — see api.py's
        async_get_version_notes docstring for the confirmed source
        behavior. Returns None (no section at all) when Dockhand can't
        confidently resolve one, or the call fails — same fail-open
        policy as _semver_advisory_section().
        """
        c = self._container()
        container_id = (c or {}).get("id")
        if not container_id or self.hass is None:
            # self.hass is None only in unit tests that never attach the
            # entity to hass — the client's session needs it.
            return None

        try:
            result = await self.coordinator.client.async_get_version_notes(
                self._env_id, container_id, []
            )
        except Exception as err:
            _LOGGER.debug(
                "Could not fetch version notes for container '%s' (env %s): %s: %s",
                self._container_name,
                self._env_id,
                type(err).__name__,
                err,
            )
            return None

        changelog_url = result.get("changelogUrl")
        if not changelog_url:
            return None

        return f"[View release notes]({changelog_url})"

    async def async_release_notes(self) -> str | None:
        """Full release notes shown in the more-info dialog — supports Markdown."""
        c = self._container()
        if not c:
            return None
        parts = []

        image_name = c.get("image")
        if image_name:
            parts.append(f"Image: {image_name}")

        newer_version_section = await self._newer_version_section(
            self._check_updates_item()
        )
        if newer_version_section:
            parts.append(newer_version_section)

        if self._scanner_enabled():
            msg = (
                "This environment scans images for vulnerabilities before"
                " updating. Depending on its configured policy, this update"
                " may be blocked if findings exceed the threshold."
            )
            parts.append(f"<ha-alert alert-type='info'>{msg}</ha-alert>")

        labels = c.get("labels") or {}
        if c.get("systemContainer"):
            msg = (
                "This is a system container and must be updated"
                " directly on the docker host."
            )
            parts.append(f"<ha-alert alert-type='warning'>{msg}</ha-alert>")
        elif _is_update_disabled_by_label(labels):
            msg = "Updates disabled via `dockhand.update=false` label."
            parts.append(f"<ha-alert alert-type='info'>{msg}</ha-alert>")

        return "\n\n".join(parts) if parts else None

    @property
    def available(self) -> bool:
        return self._container() is not None and super().available

    def _handle_coordinator_update(self) -> None:
        self._update_supported_features()
        super()._handle_coordinator_update()

    async def async_install(self, version: str | None, backup: bool, **kwargs) -> None:
        """Trigger a scanned pull-and-recreate update via Dockhand's job API.

        Only ever needs the container's current ID — never a digest — so
        this works identically whether Tier 2 has ever run for this
        container or not.
        """
        c = self._container()
        container_id = c.get("id", "") if c else ""
        if not container_id:
            raise HomeAssistantError(
                translation_domain="dockhand",
                translation_key="container_not_found",
            )

        self._attr_in_progress = True
        self._attr_update_percentage = 0
        self.async_write_ha_state()

        try:
            criteria = await self._vulnerability_criteria()
            job_id = await self.coordinator.client.async_start_batch_update_stream(
                self._env_id, [container_id], vulnerability_criteria=criteria
            )
            await self._poll_job(job_id, container_id)
        except HomeAssistantError:
            raise
        except Exception as err:
            _LOGGER.error(
                "batch-update-stream failed for container '%s' (env %s, id %s): %s: %s",
                self._container_name,
                self._env_id,
                container_id,
                type(err).__name__,
                err,
            )
            raise HomeAssistantError(
                translation_domain="dockhand",
                translation_key="action_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        finally:
            self._attr_in_progress = False
            self._attr_update_percentage = None
            self.async_write_ha_state()
        # Request a refresh so the entity state reflects the result. Also
        # nudge Tier 2 if configured, so a precise digest shows up sooner
        # than its own (up to 24h) schedule would otherwise provide.
        # Deliberately async_refresh(), not async_request_refresh() — see
        # DockhandCheckUpdatesButton's docstring in button.py for why the
        # latter can silently no-op here (a live, non-obvious debouncer
        # cooldown gotcha, not a hypothetical).
        await self.coordinator.async_refresh()
        if self._update_coordinator is not None:
            await self._update_coordinator.async_refresh()

    async def _vulnerability_criteria(self) -> str | None:
        """Fetch this environment's configured vulnerability blocking policy.

        Best-effort: falls back to None (Dockhand's own server-side default,
        "never" — scan but don't block) if the settings call fails, so a
        transient error here doesn't prevent the update itself from running.
        """
        try:
            settings = await self.coordinator.client.async_get_update_check_settings(
                self._env_id
            )
            return settings.get("vulnerabilityCriteria")
        except Exception as err:
            _LOGGER.warning(
                "Could not fetch vulnerability criteria for env %s — Dockhand"
                " will use its own default ('never': scan but don't block): %s",
                self._env_id,
                err,
            )
            return None

    async def _poll_job(self, job_id: str, container_id: str) -> None:
        """Poll GET /api/jobs/{id} until the job finishes, reporting progress.

        Dockhand's job endpoint returns the full accumulated "lines" array on
        every call rather than a stream — we re-scan it each poll, which is
        cheap since a single-container update produces at most a handful of
        lines. Raises HomeAssistantError on a blocked update, a per-container
        failure, a job-level error, or a timeout.
        """
        for _ in range(_JOB_POLL_MAX_ATTEMPTS):
            job = await self.coordinator.client.async_get_job(job_id)

            for line in job.get("lines") or []:
                data = line.get("data") or {}
                if data.get("containerId") not in (container_id, None):
                    continue

                step = data.get("step")
                new_pct = _STEP_PERCENTAGES.get(step)
                if new_pct is not None and (
                    self._attr_update_percentage is None
                    or new_pct > self._attr_update_percentage
                ):
                    self._attr_update_percentage = new_pct
                    self.async_write_ha_state()

                event_type = data.get("type")
                if event_type == "blocked":
                    reason = data.get("blockReason", "vulnerability findings")
                    raise HomeAssistantError(
                        translation_domain="dockhand",
                        translation_key="action_failed",
                        translation_placeholders={"error": f"Update blocked: {reason}"},
                    )
                if event_type == "progress" and data.get("step") == "failed":
                    raise HomeAssistantError(
                        translation_domain="dockhand",
                        translation_key="action_failed",
                        translation_placeholders={
                            "error": data.get("error", "update failed")
                        },
                    )

            status = job.get("status")
            if status == "done":
                return
            if status == "error":
                result = job.get("result") or {}
                raise HomeAssistantError(
                    translation_domain="dockhand",
                    translation_key="action_failed",
                    translation_placeholders={
                        "error": result.get("error", "update job failed")
                    },
                )

            await asyncio.sleep(_JOB_POLL_INTERVAL_SECONDS)

        raise HomeAssistantError(
            translation_domain="dockhand",
            translation_key="action_failed",
            translation_placeholders={"error": "update timed out waiting for Dockhand"},
        )
