"""Update platform for Dockhand container image updates.

Whole platform gated on CONF_ENABLE_UPDATE_ENTITIES (default True). Off
entirely disables both tiers' ENTITIES below, and the env-level bulk "Update
all" button (button.py/__init__.py) since it has nothing to act on without them
— that's the actual "backdoor to performing updates from HA" concern behind
this option. It does NOT disable the update_coordinator (Tier 2) object itself
or the env-level "Check for updates" button: that button is read-only (forces a
real registry check, refreshing Dockhand's own cached values that other things
— e.g. the stack binary sensor's pending-updates attributes — still consume
regardless of whether update entities exist), so it keeps working whenever
CONF_ENABLE_PRECISE_UPDATES is on, independent of this toggle. See
__init__.py's update_coordinator construction for that split. Some users manage
container updates outside HA entirely and don't want these entities in HA's own
update management (github.com/raetha/ha-dockhand/issues/23).

Two-tier design for entity DISPLAY (both tiers require
CONF_ENABLE_UPDATE_ENTITIES to be on — Tier 2 alone, e.g. via a manual
"Check for updates" press with entities disabled, has nothing to show
its data on):

  Tier 1 (no separate config option beyond the platform gate above):
  update entities exist for every container in every environment,
  whether or not Dockhand's scheduled update check is on for it — a
  manual check in Dockhand (or this integration's own check-updates
  calls) records pending updates just the same.
  installed_version shows the image tag (no digest available at this
  tier). latest_version flips to the container's own raw image tag when
  that's distinguishable from installed_version, else to the
  "update-pending" sentinel, when the fast coordinator's
  cheap GET /api/containers/pending-updates poll (Dockhand's own cached
  check results, no registry query of its own) flags this
  container. That same poll (DockhandFastCoordinator, see its own
  docstring) also carries hasImageUpdate/newerVersion per container, so
  Tier 1 alone answers both "is there an update" and "is there a semver
  suggestion". Install works fully at this tier —
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
  carry one.

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
                      already IS just the tag). Never installed_version
                      itself: HA shows the entity off whenever
                      latest_version == installed_version.
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
does nothing. async_release_notes()'s full semver advisory section is itself
only shown when no actionable update is pending (see
_newer_version_section() / _semver_advisory_section()) — the same gating
as latest_version above, for the same reason — and states the advisory
caveat plainly whenever it does appear. While an actionable update IS
pending, the dialog only names the newer tag in a one-line notice.

The `newer_version` state attribute carries the newerVersion tag whenever
one exists (and differs from installed_version), regardless of which
signal latest_version is showing — the only place the both-at-once case is
visible outside the release notes dialog (ha-dockhand-cards' Updates card
reads it). Comparing it with latest_version tells the two cases apart:
equal means the suggestion is the only signal (advisory-only).

Two more update signals Install can't act on, matching how Dockhand's own
containers list shows them:
  - A digest-pinned image (image:tag@sha256:...) whose tag has moved on
    (Dockhand 1.0.54+, `pinnedToDigest`). Like a newer tag it wants
    attention but needs the pin changed, so it's handled the same way:
    the entity is on (latest_version is the new digest when the precise
    check knows it, else "update-pending"), Install is withheld (see
    _advisory_only()), the `pinned_digest_moved` attribute is set, and the
    release notes say what to do. A newer version tag, when there is one
    too, is the more useful thing to show and wins latest_version.
  - An update held until the new image passes the minimum image age
    (Dockhand 1.0.52+, `releaseAgeRemainingHours`). Dockhand won't apply
    it yet, so Install is withheld, but it's coming, so the entity is on
    the same way (the new digest when known, else "update-pending"), with
    `update_held_hours` counting down from Dockhand's check — 0 once the
    wait is over, until Dockhand's next check offers it as a normal
    update. Like every signal here it's re-read from Dockhand each poll:
    once Dockhand stops reporting it (the container was updated or
    recreated another way, say), the entity turns off.

Whenever there's a pending/actionable update (with or without a
newerVersion suggestion alongside it), _newer_version_section() calls
_pending_update_changelog_section(), which asks Dockhand's version-notes
endpoint for a bare changelog link with an empty `versions` list, so a
pending update gets a changelog link even with no specific version to
attach notes to. See api.py's async_get_version_notes docstring for exactly how
Dockhand resolves this with no wanted versions.

Release notes for a newerVersion suggestion, or a bare changelog link
for a plain pending update, both come from Dockhand's own
GET /api/containers/{id}/version-notes (1.0.43+, same feature the semver
version detection is part of) via client.async_get_version_notes() —
Dockhand does the forge resolution (GitHub or self-hosted Gitea/Forgejo)
and release-matching itself, including its own unauthenticated-GitHub
rate-limit handling. Deliberately not reimplemented client-side here.

systemContainer/updateDisabled decide whether Install is offered at all,
without needing check-updates. systemContainer is Dockhand's own
precomputed field on the regular containers list already (GET
/api/containers) — the same isSystemContainer(imageName) classification
Dockhand's UI itself uses, image-name matching we don't need to
replicate and can't get out of sync with (if Dockhand adds a new system
container type, this field reflects it automatically). updateDisabled
has no such precomputed field on that endpoint, so it's still computed
client-side from the `dockhand.update` label — see
helpers._is_update_disabled_by_label, kept in sync with Dockhand's own
matching logic. Both work identically whether or not Tier 2 is enabled.

The containers list's systemContainer misses a system container whose
image Docker lists by id (`sha256:…`) rather than by name: Dockhand
classifies the name it's given, and an id names nothing. check-updates
classifies the container's configured image instead, so its own
systemContainer is used as well once a check has covered the container
(helpers._is_system_container). Dockhand itself skips a system container
in batch-update either way; this is what keeps Install from being offered.
"""

import logging
from typing import Any, override

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DockhandConfigEntry
from .const import CONF_ENABLE_UPDATE_ENTITIES, DEFAULT_ENABLE_UPDATE_ENTITIES, DOMAIN
from .coordinator import (
    DockhandFastCoordinator,
    DockhandUpdateCoordinator,
    DockhandVersionCoordinator,
)
from .helpers import (
    _all_envs,
    _container_installed_version,
    _container_update_status,
    _coordinator_env,
    _device_id_container,
    _device_id_instance,
    _find_container,
    _is_update_disabled_by_label,
    _short_digest,
    _update_held_hours,
    already_registered,
)
from .installs import DockhandInstaller, install_signal, raise_for_outcome

_LOGGER = logging.getLogger(__name__)

# No limit in Home Assistant: Installs that start together must all reach
# the install queue at once to share one Dockhand job (installs.py), and
# Dockhand updates a job's containers one after another itself.
PARALLEL_UPDATES = 0

# Cap a fetched release-notes body — some upstream release bodies embed
# screenshots/large diffs. Same bound the more-info dialog's other content
# implicitly respects; this is the one piece sourced from outside Dockhand.
_RELEASE_NOTES_MAX_CHARS = 4000


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DockhandConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up container update entities.

    Tier 1 entities are created for every container, sourced entirely
    from the fast coordinator — independent of whether Tier 2
    (update_coordinator) is configured at all.

    Removal (when a container disappears, or CONF_ENABLE_UPDATE_ENTITIES
    itself is turned off) is centralized in __init__.py's
    _cleanup_stale_registry/_build_live_sets, alongside every other
    conditionally-present entity type (images, networks, volumes,
    runtime controls, git stack entities) — not handled here. That
    function already distinguishes "environment confirmed online but
    this item is genuinely gone" from "poll failed / environment
    offline" (which must never trigger cleanup), so update entities
    reuse that same safety logic rather than duplicating it.
    """
    version = entry.runtime_data.version_coordinator
    if version.self_update_allowed:
        async_add_entities([DockhandSelfUpdateEntity(version, entry.entry_id)])

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
                    installer=data.installer,
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
    # environments.
    entry.async_on_unload(fast_coordinator.async_add_listener(_add_new_entities))


class DockhandSelfUpdateEntity(
    CoordinatorEntity[DockhandVersionCoordinator], UpdateEntity
):
    """Dockhand itself, on its device: Dockhand's own check for a newer
    release (Settings → About), which also covers installs Dockhand can't
    inspect as a container. Where Dockhand runs in an environment it
    manages, its container has an update entity of its own too: that one
    follows the image, this one the release. No Install: Dockhand's
    self-update replaces its own container, which is better started from
    Dockhand."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_release_url = "https://github.com/Finsys/dockhand/releases"

    def __init__(self, coordinator: DockhandVersionCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry_id}_instance_update"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, _device_id_instance(entry_id))}
        )

    @property
    @override
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.self_update_allowed
            and self.coordinator.self_update is not None
        )

    @property
    @override
    def installed_version(self) -> str | None:
        check = self.coordinator.self_update or {}
        return self.coordinator.data or check.get("currentVersion")

    @property
    @override
    def latest_version(self) -> str | None:
        check = self.coordinator.self_update or {}
        installed = self.installed_version
        if not check.get("updateAvailable"):
            # A failed check says nothing either way.
            return None if check.get("error") else installed
        if check.get("latestVersion"):
            return str(check["latestVersion"])
        # A moving tag (latest) has a newer image rather than a version.
        digest = str(check.get("newDigest") or "")
        return digest.removeprefix("sha256:")[:12] or None

    @override
    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        return bool((self.coordinator.self_update or {}).get("updateAvailable"))


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
        installer: DockhandInstaller,
    ) -> None:
        super().__init__(fast_coordinator)
        self._update_coordinator = update_coordinator
        self._installer = installer
        self._entry_id = entry_id
        self._env_id = env_id
        self._container_name = container_name

        self._attr_unique_id = f"{entry_id}_{env_id}_update_{container_name}"
        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, _device_id_container(entry_id, env_id, container_name))
            },
        )

        self._update_supported_features()

    def _container(self) -> dict | None:
        return _find_container(
            self.coordinator.data, self._env_id, self._container_name
        )

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {"name": self._container_name}
        # latest_version only carries the newer tag while nothing actionable
        # is pending, so a consumer showing both needs it on its own.
        newer = self._check_updates_item().get("newerVersion") or {}
        newer_tag = newer.get("tag")
        if newer_tag and newer_tag != self.installed_version:
            attrs["newer_version"] = newer_tag
            if newer.get("bump") in ("major", "minor", "patch"):
                attrs["newer_version_bump"] = newer["bump"]
            skipped = newer.get("skipped")
            # Dockhand's `skipped` includes the target tag itself. Its
            # self-update check doesn't say how many releases there were.
            if newer.get("source") != "self-update":
                attrs["newer_versions_count"] = (
                    len(skipped) if isinstance(skipped, list) and skipped else 1
                )
        item = self._check_updates_item()
        if item.get("pinnedToDigest"):
            attrs["pinned_digest_moved"] = True
        held_hours = _update_held_hours(item)
        if held_hours is not None:
            attrs["update_held_hours"] = held_hours
        return attrs

    def _check_updates_item(self) -> dict:
        """Return this container's merged update-status payload — Tier 2's
        (check-updates) item, if update_coordinator is configured and has
        data for it, MERGED with Tier 1's pending_update_details entry
        (hasImageUpdate/newerVersion, from Dockhand's cached check results —
        independent of Tier 2).

        Precedence: Tier 2's own hasUpdate/digests are authoritative
        whenever Tier 2 has a row for this container at all (it's a live
        registry check) — Tier 1 is used only to fill in newerVersion when
        Tier 2's row doesn't carry one. When Tier 2 has NO row for this
        container — Tier 2 disabled entirely, or Tier 2 ran but returned
        nothing for it (e.g. a system container check-updates itself
        excludes, or a container Tier 2 simply hasn't reached this poll)
        — the returned item is built entirely from Tier 1's detail
        instead, so hasUpdate/newerVersion still surface without ever
        needing Tier 2 (see the module docstring's "Two-tier design").

        Looked up by the container's *current* id (from Tier 1's fresh
        container list), not by name. Tier 2's data is keyed by
        container_id at fetch time; a container recreated since Tier 2
        last ran (the normal effect of an image update) gets a new id,
        so its stale entry — still sitting under the old id — simply
        won't be found here. Matching by name would keep showing a
        resolved update as pending until Tier 2's next run, up to 24 h.
        """
        c = self._container()
        if not c:
            return {}
        update_env_data = (
            _coordinator_env(self._update_coordinator.data, self._env_id)
            if self._update_coordinator is not None
            else None
        )
        pending_details = (
            _all_envs(self.coordinator.data).get(self._env_id) or {}
        ).get("pending_update_details") or {}
        return _container_update_status(c, pending_details, update_env_data)

    def _is_system(self) -> bool:
        """See helpers._is_system_container: the containers list's flag, or
        check-updates' own classification when the list misses it."""
        c = self._container()
        if not c:
            return False
        return bool(
            c.get("systemContainer")
            or self._check_updates_item().get("systemContainer")
        )

    @override
    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        """Any latest version that differs from the installed one is a signal.

        latest_version is set apart from installed_version only when Dockhand
        reports something, and the two often number differently (an image's
        version label "v2026.11.0", its tags "4.0"), so Home Assistant's own
        comparison could call a real update older and turn the entity off.
        """
        return latest_version != installed_version

    def _advisory_only(self, item: dict) -> bool:
        """True when the only reason installed_version != latest_version is
        something Install can't apply: a newer version tag (the container's
        pinned tag has to change — see the module docstring's "Semver
        'newer version tag' detection is advisory only" section) or a moved
        digest behind a digest-pinned image (the pin has to change; pulling
        it returns the same image). `item` is the merged
        _check_updates_item() result, so this reflects Tier 1 whenever Tier
        2 has no row for the container. Install must not be offered then:
        it would only re-pull what the container already runs."""
        if item.get("hasUpdate") or self._pending_via_dockhand_cache():
            return False
        return (
            bool((item.get("newerVersion") or {}).get("tag"))
            or bool(item.get("pinnedToDigest"))
            or _update_held_hours(item) is not None
        )

    def _update_supported_features(self) -> None:
        c = self._container() or {}
        labels = c.get("labels") or {}
        update_disabled = _is_update_disabled_by_label(labels)
        if (
            update_disabled
            or self._is_system()
            or self._advisory_only(self._check_updates_item())
        ):
            self._attr_supported_features = UpdateEntityFeature.RELEASE_NOTES
        else:
            self._attr_supported_features = (
                UpdateEntityFeature.INSTALL
                | UpdateEntityFeature.RELEASE_NOTES
                | UpdateEntityFeature.PROGRESS
            )

    @property
    @override
    def installed_version(self) -> str | None:
        return _container_installed_version(
            self._container(), self._check_updates_item()
        )

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
        return c is not None and c.get("id") in pending_ids

    @property
    @override
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
            # is configured. Not installed_version: HA renders STATE_OFF
            # whenever latest_version == installed_version, which would
            # hide a genuinely pending update.
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
                return str(raw_tag)
            return "update-pending"
        if self._pending_via_dockhand_cache():
            # Deliberately not a real digest — see module docstring. This
            # is Tier 1's own signal, present whether or not Tier 2 (real
            # digest data) is configured at all. Checked before newerVersion
            # for the same reason hasUpdate is: it keeps Install enabled
            # (see _advisory_only()), so showing the semver target
            # here would advertise a version Install can't deliver.
            return "update-pending"
        newer_tag = (item.get("newerVersion") or {}).get("tag")
        if newer_tag:
            newer_tag = str(newer_tag)
            # No actionable update right now — safe to surface the semver
            # suggestion. _update_supported_features() withholds Install
            # for this case via _advisory_only(). Once the container
            # catches up to its pinned tag's latest content, this naturally
            # takes over.
            return newer_tag
        if item.get("pinnedToDigest") or _update_held_hours(item) is not None:
            # Not installable either (see _advisory_only()). The precise
            # check knows the new digest; Dockhand's cached check doesn't.
            new_digest = item.get("newDigest", "")
            return _short_digest(new_digest) if new_digest else "update-pending"
        return self.installed_version

    def _scanner_enabled(self) -> bool:
        """Return True if vulnerability scanning is enabled on this environment."""
        fast_data = _all_envs(self.coordinator.data)
        stats = (fast_data.get(self._env_id) or {}).get("stats") or {}
        return bool(stats.get("scannerEnabled", False))

    @property
    @override
    def release_summary(self) -> str | None:
        """Not used — release notes cover all warning content."""
        return None

    async def _newer_version_section(self, item: dict) -> str | None:
        """Pick which "what's coming" section, if any, belongs at the top
        of the release notes dialog for this container's merged
        update-status item. An actionable update (hasUpdate, or Tier 1's
        own pending-updates cache in the divergent-Tier-2 case) always
        takes precedence over a semver newerVersion suggestion — the same
        precedence latest_version and _advisory_only() apply — so
        the dialog never describes a different target than Install
        delivers:

          1. Actionable update pending: a bare changelog link via
             _pending_update_changelog_section(). If a newerVersion
             suggestion is ALSO present, a one-line notice naming its tag
             comes first, so the bigger (non-actionable) update isn't
             invisible until this one is applied. Deliberately just the
             tag — no release notes body or skipped count for a version
             Install won't move to; the full advisory section takes over
             once the actionable update resolves.

          2. Only a newerVersion suggestion: the full advisory section via
             _semver_advisory_section().

        Returns None when neither applies.
        """
        newer = item.get("newerVersion") or {}
        tag = newer.get("tag")

        if item.get("hasUpdate") or self._pending_via_dockhand_cache():
            lines = []
            if tag:
                lines.append(
                    f"A newer version tag is also available: **{tag}**."
                    " Moving to it requires updating the tag in your compose"
                    " file or container config."
                )
            changelog = await self._pending_update_changelog_section()
            if changelog:
                lines.append(changelog)
            return "\n\n".join(lines) or None

        if tag:
            return await self._semver_advisory_section(tag, newer)

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
        """Bare changelog-link section for a pending/actionable update —
        there's no target version to fetch notes for, since Install just
        re-pulls the current tag (see _newer_version_section's own
        docstring).

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

    @override
    async def async_release_notes(self) -> str | None:
        """Full release notes shown in the more-info dialog — supports Markdown."""
        c = self._container()
        if not c:
            return None
        parts = []

        image_name = c.get("image")
        if image_name:
            parts.append(f"Image: {image_name}")

        item = self._check_updates_item()
        newer_version_section = await self._newer_version_section(item)
        if newer_version_section:
            parts.append(newer_version_section)
        if item.get("pinnedToDigest"):
            msg = (
                "**Pinned to a digest.** The image's tag has moved to a new"
                " digest, but this container is pinned to the old one. To"
                " update it, change the digest in its compose file or run"
                " command; Install would only pull the pinned image again."
            )
            parts.append(f"<ha-alert alert-type='warning'>{msg}</ha-alert>")
        held_hours = _update_held_hours(item)
        if held_hours:
            msg = (
                f"**Update held:** {held_hours} hour(s) left of the minimum"
                " image age set in Dockhand. It can be installed after that."
            )
            parts.append(f"<ha-alert alert-type='info'>{msg}</ha-alert>")
        elif held_hours == 0:
            msg = (
                "**Update held:** the new image has reached the minimum image"
                " age set in Dockhand. It can be installed once Dockhand"
                " next checks for updates (or after **Check for updates**)."
            )
            parts.append(f"<ha-alert alert-type='info'>{msg}</ha-alert>")

        if self._scanner_enabled():
            msg = (
                "This environment scans images for vulnerabilities before"
                " updating. Depending on its configured policy, this update"
                " may be blocked if findings exceed the threshold."
            )
            parts.append(f"<ha-alert alert-type='info'>{msg}</ha-alert>")

        labels = c.get("labels") or {}
        if self._is_system():
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
    @override
    def available(self) -> bool:
        return self._container() is not None and super().available

    @override
    def _handle_coordinator_update(self) -> None:
        self._update_supported_features()
        super()._handle_coordinator_update()

    @override
    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Pull and recreate the container through Dockhand's update job,
        shared with any other Install in the environment that starts at
        the same time (see installs.py). Only needs the container's current
        id, never a digest, so it works with or without precise updates.
        """
        c = self._container()
        container_id = c.get("id", "") if c else ""
        if not container_id:
            raise HomeAssistantError(
                translation_domain="dockhand",
                translation_key="container_not_found",
            )
        outcomes = await self._installer.async_install(self._env_id, [container_id])
        raise_for_outcome(outcomes[container_id])

    @property
    @override
    def in_progress(self) -> bool:
        return self._install_progress() is not None

    @property
    @override
    def update_percentage(self) -> int | None:
        return self._install_progress()

    def _install_progress(self) -> int | None:
        c = self._container()
        container_id = c.get("id") if c else None
        if not container_id:
            return None
        return self._installer.progress(self._env_id, container_id)

    @override
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                install_signal(self._entry_id, self._env_id),
                self.async_write_ha_state,
            )
        )

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        # Nothing here is keyed on entity_id, so a rename can happen in
        # place (HA 2026.11+) instead of removing and re-adding the entity,
        # which defining async_added_to_hass otherwise forces. Only ever
        # called by HA versions that have this method, which is also why
        # mypy (checking against an older one) can't see it yet.
        super().async_entity_id_changed(old_entity_id)  # type: ignore[misc, unused-ignore]
