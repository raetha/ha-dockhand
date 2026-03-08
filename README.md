[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/v/release/raetha/ha-dockhand?style=plastic)](https://github.com/raetha/ha-dockhand/releases)

# Dockhand for Home Assistant

Monitor and control your Docker environments through **[Dockhand](https://dockhand.pro)** — a modern Docker management UI. This integration exposes environments, containers, stacks, networks, images, volumes, and schedules as Home Assistant devices and entities, using the same API as the Dockhand web UI.

No cloud services are used. Supports **local user authentication** including **MFA (TOTP)**.

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
   - **Username** and **Password** (must be a local Dockhand user — see below)
   - **Fast poll interval** — default 60 s (stats, containers, stacks)
   - **Slow poll interval** — default 600 s (optional features)
   - Which optional features to enable (schedules, images, volumes, networks)
   - **Verify SSL certificate** — uncheck only if using a self-signed cert
4. If MFA is enabled, enter your 6-digit TOTP code when prompted

After setup, use **Configure** (the cog) to adjust poll intervals and feature flags, or **Reconfigure** to change the URL or credentials.

---

## Configuration parameters

### Setup fields (entered once at install time)

| Field | Description | Default |
|---|---|---|
| **API URL** | Full URL to your Dockhand server, e.g. `http://dockhand.local:3000` | — |
| **Username** | Local Dockhand account username | — |
| **Password** | Local Dockhand account password | — |
| **Fast poll interval** | How often (seconds) to refresh container states, stacks, and environment stats | 60 |
| **Slow poll interval** | How often (seconds) to refresh images, volumes, networks, and schedules | 600 |
| **Enable schedules** | Create entities for Dockhand scheduled tasks | off |
| **Enable images** | Create entities for Docker images on each host | off |
| **Enable volumes** | Create entities for Docker volumes on each host | off |
| **Enable networks** | Create entities for Docker networks on each host | off |
| **Verify SSL certificate** | Validate the server's SSL/TLS certificate. Uncheck only if your Dockhand instance uses a self-signed certificate | on |

### Options (adjustable via Configure without removing the integration)

All fields except **API URL**, **Username**, and **Password** can be changed at any time through the **Configure** button on the integration card. Changes take effect on the next coordinator refresh.

### Reconfigure (change URL or credentials)

Use **Reconfigure** (three-dot menu → Reconfigure) to change the **API URL**, **Username**, or **Password**. The integration re-authenticates immediately and updates the stored session. Leave the password field blank to keep the existing password.

---

## Authentication

### Local user required
OIDC/SSO accounts are **not supported**. The integration authenticates with the same session-cookie login the web UI uses, which requires a local Dockhand user. Create one under **Settings → Authentication → Local Users** in Dockhand.

### MFA support
If your local user has MFA enabled, the integration will prompt for your TOTP code during setup and whenever the session expires. HA stores the session cookie and re-uses it automatically; it only asks for a code again when the session expires or credentials change.

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

Entities update automatically when their coordinator refreshes. If a fetch fails, entities remain at their last known value and are marked unavailable after the coordinator's built-in retry threshold. Both coordinators handle session expiry transparently — they will attempt re-authentication and retry the failed fetch before raising an unavailable state.

## Troubleshooting

**Cannot connect**
Check the API URL is reachable from the HA host. Confirm you are using a local user, not OIDC.

**MFA prompted on every Reconfigure**
Dockhand validates the session when settings change. If your user has MFA, one code per reconfigure is expected.

**No entities appear after setup**
Check HA logs for errors containing `dockhand`. Ensure the user account has permission to view all environments.

**Schedules show but no "run" button**
Intentional — the Dockhand API has no run-now endpoint for schedules. The per-schedule device structure is preserved for when this is added.

---

## Requirements

- Home Assistant 2026.3 or later
- Dockhand reachable from the HA host
- A local Dockhand user account (OIDC not supported)

---

## Notes

- All data is fetched locally — no external cloud services
- The session cookie is stored in the HA config entry, not the password itself
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
