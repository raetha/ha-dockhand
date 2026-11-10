from dataclasses import dataclass
from datetime import timedelta

DOMAIN = "dockhand"

CONF_API_URL = "api_url"
CONF_API_TOKEN = "api_token"
CONF_ENABLE_SCHEDULES = "enable_schedules"
CONF_ENABLE_IMAGES = "enable_images"
CONF_ENABLE_VOLUMES = "enable_volumes"
CONF_ENABLE_NETWORKS = "enable_networks"
CONF_ENABLE_UPDATE_ENTITIES = "enable_update_entities"
CONF_ENABLE_PRECISE_UPDATES = "enable_precise_updates"
CONF_ENABLE_RUNTIME_CONTROLS = "enable_runtime_controls"
CONF_ENABLE_RESOURCE_STATS = "enable_resource_stats"
CONF_VERIFY_SSL = "verify_ssl"

# Everything the Configure dialog sets. These live in entry.options; entry.data
# holds only the connection details (URL, token, SSL verification).
OPTION_KEYS = (
    CONF_ENABLE_SCHEDULES,
    CONF_ENABLE_IMAGES,
    CONF_ENABLE_VOLUMES,
    CONF_ENABLE_NETWORKS,
    CONF_ENABLE_UPDATE_ENTITIES,
    CONF_ENABLE_PRECISE_UPDATES,
    CONF_ENABLE_RUNTIME_CONTROLS,
    CONF_ENABLE_RESOURCE_STATS,
)

# Session-cookie credentials from before API tokens: read only so __init__.py
# can ask an old entry for a token and drop them.
_LEGACY_CONF_USERNAME = "username"
_LEGACY_CONF_PASSWORD = "password"
_LEGACY_CONF_SESSION_COOKIE = "session_cookie"

# Config entry schema version, (major, minor). Bump the minor for any change
# to stored settings; bump the major only in a major integration release (see
# docs/architecture.md §4 for the full lifecycle this drives).
SCHEMA_VERSION = 2
SCHEMA_MINOR_VERSION = 3


@dataclass(frozen=True)
class RenamedOption:
    """A stored setting renamed at schema version (major, minor).

    How long each rename is kept working follows from (major, minor) alone,
    so nothing here has to be retired by hand at the right moment:
      - Downgrade support (stored config): only while (major, minor) is the
        current schema version is the old name saved alongside the new one,
        for releases on the schema version just before it, which read only
        the old name. The next schema bump, minor or major, stops this, and
        the copies left in stored entries are cleaned up by the same pass
        that wrote them. So stored entries never carry more than one schema
        version's worth of old names. (Not in a major's first minor: no
        release of the previous major can load the entry at all.)
      - Upgrade support (code only): while `major` is the current or the
        previous schema major, an entry still using the old name is
        translated on upgrade, however many releases it skipped. Older than
        that, the entry can't be migrated at all (see async_migrate_entry),
        so the rename is dead code — tests/test_init.py fails until it's
        deleted from RENAMED_OPTIONS.
    """

    old: str
    new: str
    major: int
    minor: int


RENAMED_OPTIONS: tuple[RenamedOption, ...] = (
    # 1.8.0: only ever controlled the precise (Tier 2) update checks, once
    # update entities themselves became always-on.
    RenamedOption("enable_updates", "enable_precise_updates", 2, 1),
    # 1.11.0: now also creates the stack resource stats sensors.
    RenamedOption("enable_container_stats", "enable_resource_stats", 2, 2),
    # 1.11.0: pairs with poll_interval_slow; alone it read as the only interval.
    RenamedOption("poll_interval", "poll_interval_fast", 2, 2),
    # 1.11.0: only ever controlled the precise (Tier 2) registry checks.
    RenamedOption("poll_interval_updates", "poll_interval_precise_updates", 2, 2),
)


@dataclass(frozen=True)
class RemovedOption:
    """A stored setting nothing reads any more, from schema (major, minor).

    Its stored value is kept while (major, minor) is the current schema
    version, since releases on the version before it still read it, and
    dropped by the next schema bump, minor or major.
    """

    name: str
    major: int
    minor: int


REMOVED_OPTIONS: tuple[RemovedOption, ...] = (
    # 2.0.0: Home Assistant doesn't let users set polling intervals.
    RemovedOption("poll_interval_fast", 2, 3),
    RemovedOption("poll_interval_slow", 2, 3),
    RemovedOption("poll_interval_precise_updates", 2, 3),
)


SCHEMA = (SCHEMA_VERSION, SCHEMA_MINOR_VERSION)


def renames_to_translate(schema: tuple[int, int] = SCHEMA) -> dict[str, str]:
    """old -> new for every rename an upgrade still has to translate."""
    return {r.old: r.new for r in RENAMED_OPTIONS if r.major >= schema[0] - 1}


def removed_to_keep(schema: tuple[int, int] = SCHEMA) -> frozenset[str]:
    """Removed settings whose stored value is still kept for the previous
    schema version's releases."""
    return frozenset(r.name for r in REMOVED_OPTIONS if (r.major, r.minor) == schema)


def removed_to_drop(schema: tuple[int, int] = SCHEMA) -> frozenset[str]:
    """Removed settings to delete from stored entries."""
    return frozenset(r.name for r in REMOVED_OPTIONS if (r.major, r.minor) < schema)


def renames_to_mirror(schema: tuple[int, int] = SCHEMA) -> dict[str, str]:
    """old -> new for every rename whose old name is still saved too: those
    made at exactly this schema version, for releases on the one before it
    (which can still load the entry, and read only the old name)."""
    return {
        r.old: r.new
        for r in RENAMED_OPTIONS
        if (r.major, r.minor) == schema and r.minor > 1
    }


# Container state, stats and update flags.
FAST_POLL_INTERVAL = timedelta(minutes=1)
# Images, volumes, networks, schedules, git stacks, host details.
SLOW_POLL_INTERVAL = timedelta(minutes=10)
# Precise update checks: real registry queries for every container.
PRECISE_UPDATES_POLL_INTERVAL = timedelta(hours=24)
# Dockhand's own version: it only changes when Dockhand is upgraded, which
# restarts it, and the response is about 100 KB.
VERSION_POLL_INTERVAL = timedelta(hours=6)
DEFAULT_ENABLE_SCHEDULES = False
DEFAULT_ENABLE_IMAGES = False
DEFAULT_ENABLE_VOLUMES = False
DEFAULT_ENABLE_NETWORKS = False
# Default True: preserves existing behavior for upgrading users, since
# Tier 1 update entities have been unconditionally created since 1.8.0
# with no way to opt out (github.com/raetha/ha-dockhand/issues/23) — this
# is the option that was missing, not a replacement for
# CONF_ENABLE_PRECISE_UPDATES (which only ever controlled Tier 2 and
# still does; its 1.8.0 rename is in RENAMED_OPTIONS above). This one
# gates the update platform itself —
# Tier 1 and Tier 2 both — off entirely.
DEFAULT_ENABLE_UPDATE_ENTITIES = True
DEFAULT_ENABLE_PRECISE_UPDATES = False
# Runtime controls (number/select entities for update-runtime) require an
# extra GET .../inspect call per stack-less container per slow-poll cycle —
# unlike other DIAGNOSTIC entities, this has a real, non-trivial API cost,
# so it's gated the same way images/networks/volumes are.
DEFAULT_ENABLE_RUNTIME_CONTROLS = False
DEFAULT_ENABLE_RESOURCE_STATS = False

PLATFORMS = [
    "sensor",
    "switch",
    "binary_sensor",
    "button",
    "update",
    "number",
    "select",
    "event",
]

# Docker container events the per-container event entity fires, matching
# Home Assistant's Portainer integration. Docker sends a health check
# result as "health_status: <status>".
CONTAINER_EVENT_TYPES = [
    "die",
    "health_status_healthy",
    "health_status_starting",
    "health_status_unhealthy",
    "kill",
    "oom",
    "pause",
    "restart",
    "start",
    "stop",
    "unpause",
    "update",
]
