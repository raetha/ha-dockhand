[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/v/release/raetha/ha-dockhand?style=plastic)](https://github.com/raetha/ha-dockhand/releases)

# Dockhand for Home Assistant

Monitor and control your Docker environments through **[Dockhand](https://dockhand.pro)** — a modern Docker management UI. This integration exposes environments, containers, stacks, networks, images, volumes, and schedules as Home Assistant devices and entities, using the same API as the Dockhand web UI.

No cloud services are used. Supports **API token authentication** and works with Dockhand instances where authentication is disabled.

---

## Installation

### HACS (Recommended)

This integration is not yet in the default HACS catalog. You can add it as a custom repository:

1. Open HACS in Home Assistant
2. Go to **Integrations**
3. Click the **⋮** menu → **Custom repositories**
4. Enter the repository URL: `https://github.com/raetha/ha-dockhand`
5. Set category to **Integration** and click **Add**
6. Find **Dockhand** in the integration list and install it
7. Restart Home Assistant

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=raetha&repository=ha-dockhand&category=integration)

### Manual

1. Copy the `custom_components/dockhand/` folder into `<HA config>/custom_components/dockhand/`
2. Restart Home Assistant

---

## Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Dockhand**
3. Enter:
   - **API URL** — e.g. `http://dockhand.local:3000`
   - **Fast poll interval** — default 60 s (stats, containers, stacks)
   - **Slow poll interval** — default 600 s (optional features)
   - Which optional features to enable (schedules, images, volumes, networks)
   - **Verify SSL certificate** — uncheck only if using a self-signed cert
4. The integration probes the server. If authentication is enabled it will prompt for an **API token** — generate one in Dockhand under **Profile → API tokens**, then paste it in

After setup, use **Configure** (the cog) to adjust poll intervals and feature flags, or **Reconfigure** to change the URL or API token.

---

## Configuration parameters

### Setup fields (entered once at install time)

| Field | Description | Default |
|---|---|---|
| **API URL** | Full URL to your Dockhand server, e.g. `http://dockhand.local:3000` | — |
| **API Token** | A Dockhand API token starting with `dh_`. Only requested if the server requires authentication. Generate one under **Profile → API tokens** | — |
| **Fast poll interval** | How often (seconds) to refresh container states, stacks, and environment stats | 60 |
| **Slow poll interval** | How often (seconds) to refresh images, volumes, networks, and schedules | 600 |
| **Enable schedules** | Create entities for Dockhand scheduled tasks | off |
| **Enable images** | Create entities for Docker images on each host | off |
| **Enable volumes** | Create entities for Docker volumes on each host | off |
| **Enable networks** | Create entities for Docker networks on each host | off |
| **Verify SSL certificate** | Validate the server's SSL/TLS certificate. Uncheck only if your Dockhand instance uses a self-signed certificate | on |

### Options (adjustable via Configure without removing the integration)

All fields except **API URL** and **API Token** can be changed at any time through the **Configure** button on the integration card. Changes take effect on the next coordinator refresh.

### Reconfigure (change URL or credentials)

Use **Reconfigure** (three-dot menu → Reconfigure) to change the **API URL**, **API Token**, or feature flags. The integration re-probes the server immediately; if authentication is required it will prompt for a token.

---

## Authentication

### API token (recommended)
When Dockhand authentication is enabled, the integration authenticates using a **Bearer token** (`dh_...`). Tokens do not have a session timeout, which eliminates the daily re-authentication prompts that affected MFA users with the previous session-cookie approach.

To generate a token:
1. Open the Dockhand UI and click your avatar in the sidebar
2. Scroll to **API tokens**
3. Click **Generate token**, give it a name, and optionally set an expiry
4. Copy the token immediately — it is shown only once
5. Paste it into the HA integration setup or re-authentication prompt

> **Requires Dockhand ≥ 1.0.26.** Token authentication was introduced in 1.0.25 but had a bug with enterprise licences that was fixed in 1.0.26.

### No-auth installs
If Dockhand authentication is fully disabled, no token is needed. The integration detects this automatically during setup and skips the token prompt. If you later enable authentication in Dockhand, HA will surface a re-authentication prompt the next time a poll fails.

### Re-authentication
If a token is revoked or expires, the integration will surface a re-authentication notification in HA. Go to **Settings → Devices & Services → Dockhand → Re-authenticate**, generate a new token in Dockhand, and paste it in.

---

## Device model

The integration uses a **grouped device hierarchy** that keeps the device list manageable regardless of how many containers and stacks you have.

```
Heimdall                               ← Environment device
│   model: Dockhand Environment
├── Heimdall – Containers              ← Group device
│   ├── Heimdall – traefik             ← Container device
│   │   model: Docker Container
│   │   ├── sensor.State
│   │   ├── sensor.Health
│   │   ├── switch.Container
│   │   └── button.Restart
│   └── Heimdall – nginx  (same)
├── Heimdall – Stacks                  ← Group device
│   ├── Heimdall – proxy               ← Stack device
│   │   model: Compose Stack
│   │   ├── sensor.Status
│   │   ├── switch.Running
│   │   └── button.Restart
│   └── Heimdall – monitoring  (same)
├── Heimdall – Networks  (if enabled)  ← Group device
│   └── sensor.bridge                  ← one entity per network (no sub-devices)
│   └── sensor.host
├── Heimdall – Volumes  (if enabled)   ← Group device
│   └── sensor.my_volume               ← one entity per volume (no sub-devices)
└── Heimdall – Images  (if enabled)    ← Group device
    └── sensor.traefik_latest          ← one entity per image (no sub-devices)

sensor.CPU_usage, sensor.Memory_usage, sensor.Containers_running
binary_sensor.Online                   ← on the Environment device

Schedules  (if enabled)                ← Global hub device (not env-specific)
└── auto-update                        ← per-schedule device
    ├── sensor.Next_run
    └── sensor.Last_status
```

Each device in the list shows its **Type** (`model` field), so it's easy to distinguish containers from stacks, and group devices from individual ones. Every device also has a direct **open in Dockhand** link that takes you straight to the corresponding page.

Individual resource devices (containers, stacks, networks, volumes) are prefixed with their environment name — for example `Heimdall – traefik` rather than just `traefik`. This makes it easy to identify which host a resource belongs to in the entity picker and automation editor, especially when multiple environments run containers or stacks with the same name.

### Portainer users
If you're migrating from the Portainer integration, this integration follows the same structural patterns — one environment device, child devices for containers and stacks, a control switch and `Restart` button per container and per stack. Container and stack devices are named `{env} – {resource}` (e.g. `Heimdall – traefik`) to disambiguate across environments.

---

## Entities reference

### Environment (always on, 60 s)
| Entity | Type | Notes |
|---|---|---|
| Online | binary_sensor | Connectivity device class |
| CPU usage | sensor | % |
| Memory usage | sensor | %, with used/total GB attributes |
| Containers running | sensor | with total/stopped/unhealthy attributes |
| Images | sensor | count of Docker images on the environment |

### Container (always on, 60 s)
| Entity | Type | Notes |
|---|---|---|
| State | sensor | running / exited / paused / etc. |
| Health | sensor | healthy / unhealthy / starting / none |
| Container | switch | turn on = start, turn off = stop |
| Restart | button | restarts running container (use Container to start stopped) |

### Stack (always on, 60 s)
| Entity | Type | Notes |
|---|---|---|
| Status | sensor | running / partial / stopped |
| Running | switch | turn on = start, turn off = stop |
| Restart | button | restarts running stack (use Running to start stopped) |

### Network (optional, 600 s)

One entity per network, living under the **{env} – Networks** group device.

| Entity | Type | Notes |
|---|---|---|
| *network-name* | sensor | Named for the network (e.g. `bridge`); state is connected container count; attributes include driver, scope, subnet, and connected container names/IPs |

### Volume (optional, 600 s)

One entity per volume, living under the **{env} – Volumes** group device.

| Entity | Type | Notes |
|---|---|---|
| *volume-name* | sensor | Named for the volume; state is connected container count (0 = unused/dangling); attributes include in_use bool, container list, driver, scope, mountpoint, labels, and created timestamp |

### Schedule (optional, 600 s)

Two entities per schedule, parented to a per-schedule device under the **Schedules** hub. The per-schedule device structure is preserved to future-proof for Dockhand API additions (run-now, enable/disable).

| Entity | Type | Notes |
|---|---|---|
| Next run | sensor | TIMESTAMP device class; suitable for time-based automation triggers. Attributes include cron expression, enabled state, environment name, and schedule type |
| Last status | sensor | DIAGNOSTIC; string value (`success`, `failed`, etc.) — use a `state` trigger for clean failure-alert automations. Attributes include triggered_by, triggered_at, duration_ms, error_message |

> Schedules are **read-only**. Dockhand does not expose a run-now API endpoint, so no action button is provided. The per-schedule device is kept for when this changes.

---

## Container and Stack controls

| What you want | How to do it |
|---|---|
| Start a stopped container | Turn **Container** switch **on** |
| Stop a running container | Turn **Container** switch **off** |
| Start a stopped stack | Turn **Stack** switch **on** |
| Stop a running stack | Turn **Stack** switch **off** |
| Restart a container or stack | Press **Restart** button |

The Restart button only works when the container or stack is already running — Docker cannot restart a stopped one. If a container has stopped unexpectedly, turn the **Container** switch on first, then use **Restart** if needed.

---

## Example automation

```yaml
automation:
  - alias: "Alert when container goes down"
    triggers:
      - trigger: state
        entity_id: sensor.traefik_state
        to: exited
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "Container down"
          message: "traefik has stopped"
```

---

## Data Updates

Dockhand uses two polling coordinators with independent intervals to balance responsiveness against API load:

**Fast coordinator** (default 60 s, configurable) fetches:
- Environment dashboard stats (CPU, memory, container/stack/image/volume/network counts)
- Full container list with state, image, and resource details
- Full stack list with status and container counts

**Slow coordinator** (default 600 s, configurable) fetches:
- Per-environment detailed data for optional features: Images, Networks, Volumes
- Global schedule list

Entities update automatically when their coordinator refreshes. If a fetch fails, entities remain at their last known value and are marked unavailable after the coordinator's built-in retry threshold. Both coordinators handle token errors transparently — a 401 response surfaces a re-authentication notification in HA rather than silently retrying.

## Troubleshooting

**Cannot connect**
Check the API URL is reachable from the HA host. If authentication is enabled, confirm your API token starts with `dh_` and was copied in full.

**Entity IDs have a `_2` or `_3` suffix after a container or image update**
When a container is recreated with a new image, or a new image is pulled before the old one is pruned, both the old and new objects briefly exist simultaneously. HA assigns a suffix to the new entity to avoid a collision. Once the old object is gone (container removed, image pruned) and the integration has reloaded or polled, the stale entity is cleaned up automatically. To reclaim the clean entity ID, go to **Settings → Devices & Services → ⋮ → Recreate entity IDs** on the Dockhand integration card. HA will rename any suffixed entity whose "natural" ID is now free. Any automations or dashboard cards referencing the suffixed ID will need to be updated after the rename.

**No entities appear after setup**
Check HA logs for errors containing `dockhand`. Ensure the user account has permission to view all environments.

**Schedules show but no "run" button**
Intentional — the Dockhand API has no run-now endpoint for schedules. The per-schedule device structure is preserved for when this is added.

---

## Requirements

- Home Assistant 2026.3 or later (requires Python 3.14)
- Dockhand ≥ 1.0.26 (for API token authentication; no-auth installs work on any version)
- Dockhand reachable from the HA host

---

## Notes

- All data is fetched locally — no external cloud services
- The API token is stored securely in the HA config entry; credentials (username/password) are never stored
- The Restart button only works on *running* containers/stacks
- Disable **Verify SSL certificate** only if using a self-signed certificate on the Dockhand server

---

## Attribution

This integration was developed by **[@raetha](https://github.com/raetha)** with design assistance and code generation by **[Claude](https://claude.ai)** (Anthropic). The integration architecture and entity model are inspired by the official [Portainer integration](https://www.home-assistant.io/integrations/portainer/) added to Home Assistant core in 2025.10.

---

## License

MIT

## Removal

To remove the Dockhand integration from Home Assistant:

1. Go to **Settings → Devices & services**.
2. Find the **Dockhand** integration card and click on it.
3. Click the three-dot menu (⋮) and select **Delete**.

All devices, entities, and configuration data created by this integration will be removed
automatically. No edits to `configuration.yaml` are required. Any automations or dashboard
cards referencing Dockhand entities should be updated or removed manually.

### Uninstalling via HACS

After deleting the integration from Settings, go to **HACS → Integrations**, find
**Dockhand**, and click **Remove**. Restart Home Assistant when prompted.
