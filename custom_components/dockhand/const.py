from __future__ import annotations

DOMAIN = "dockhand"

CONF_API_URL = "api_url"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_POLL_INTERVAL = "poll_interval"
CONF_POLL_INTERVAL_SLOW = "poll_interval_slow"
CONF_ENABLE_SCHEDULES = "enable_schedules"
CONF_ENABLE_IMAGES = "enable_images"
CONF_ENABLE_VOLUMES = "enable_volumes"
CONF_ENABLE_NETWORKS = "enable_networks"
CONF_VERIFY_SSL = "verify_ssl"
CONF_SESSION_COOKIE = "session_cookie"

DEFAULT_POLL_INTERVAL = 60
DEFAULT_POLL_INTERVAL_SLOW = 600
DEFAULT_ENABLE_SCHEDULES = False
DEFAULT_ENABLE_IMAGES = False
DEFAULT_ENABLE_VOLUMES = False
DEFAULT_ENABLE_NETWORKS = False

PLATFORMS = ["sensor", "switch", "binary_sensor", "button"]
