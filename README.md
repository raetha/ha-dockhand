[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![Release](https://img.shields.io/github/v/release/raetha/ha-dockhand?style=for-the-badge)](https://github.com/raetha/ha-dockhand/releases)
[![Validation](https://img.shields.io/github/actions/workflow/status/raetha/ha-dockhand/ci.yml?label=validation&style=for-the-badge)](https://github.com/raetha/ha-dockhand/actions/workflows/ci.yml)
[![Installs](https://img.shields.io/badge/dynamic/json?style=for-the-badge&color=blue&label=installs&cacheSeconds=3600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.dockhand.total)](https://analytics.home-assistant.io/custom_integrations.json)

![Dockhand logo](custom_components/dockhand/brand/logo.png)

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
3. Enter the **API URL** (e.g. `http://dockhand.local:3000`) and SSL preference
4. The integration probes the server. If authentication is enabled you'll be prompted for an **API token** — generate one in Dockhand under **Profile → API tokens**
5. Set poll intervals and enable any optional features (schedules, images, volumes, networks, container updates). All of these can be changed later via **Configure**

To change the URL, SSL setting, or API token after setup, use **Reconfigure** (three-dot menu on the integration card)

---

## Configuration parameters

### Setup fields (entered once at install time)

| Field | Description | Default |
|---|---|---|
| **API URL** | Full URL to your Dockhand server, e.g. `http://dockhand.local:3000` | — |
| **Verify SSL certificate** | Validate the server's SSL/TLS certificate. Uncheck only if your Dockhand instance uses a self-signed certificate | on |
| **API Token** | A Dockhand API token starting with `dh_`. Only prompted if the server requires authentication. Generate one under **Profile → API tokens** | — |

### Options (adjustable via Configure)

The following can be changed at any time via the **Configure** button on the integration card, without removing the integration. Changes take effect on the next coordinator refresh.

| Field | Description | Default |
|---|---|---|
| **Fast poll interval** | How often (seconds) to refresh container states, stacks, and environment stats. Minimum: 10 | 60 |
| **Slow poll interval** | How often (seconds) to refresh images, volumes, networks, and schedules. Minimum: 30 | 600 |
| **Enable schedules** | Create entities for Dockhand scheduled tasks | off |
| **Enable images** | Create entities for Docker images on each host | off |
| **Enable volumes** | Create entities for Docker volumes on each host | off |
| **Enable networks** | Create entities for Docker networks on each host | off |
| **Enable container updates** | Create update entities for each container, showing image update availability and allowing one-click updates via Dockhand's `batch-update` API | off |
| **Update check interval** | How often (seconds) to check container registries for image updates. Each check queries the registry for every container — keep this infrequent (minimum: 300). Only shown when container updates are enabled | 86400 |

### Reconfigure (change URL, SSL, or API token)

Use **Reconfigure** (three-dot menu → Reconfigure) to change the **API URL**, **Verify SSL** setting, or **API Token**. The token field is pre-populated and masked — clear it to disable authentication (you will be re-prompted if the server still requires it), or enter a new value to rotate credentials. The integration re-probes the server on save.

---

## Authentication

### API token (recommended)
When Dockhand authentication is enabled, the integration authenticates using a **Bearer token** (`dh_...`). Tokens do not expire by default (unless you set an expiry when generating), which means no periodic re-authentication prompts.

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
myenv                                       ← Environment device
├── myenv – Containers                      ← Group device (freestanding containers only)
│   └── myenv – Containers – mycontainer   ← Container device
│       ├── switch  (primary — no suffix)
│       ├── sensor.State
│       ├── sensor.Health              ← only if container has a healthcheck
│       ├── button.Restart
│       ├── update                     ← if container updates enabled
│       └── (diagnostic, disabled by default)
│           ├── sensor.CPU usage
│           ├── sensor.Memory usage
│           ├── sensor.Memory usage %
│           ├── sensor.Memory limit
│           ├── sensor.Network in / Network out
│           └── sensor.Disk read / Disk write
├── myenv – Stacks                          ← Group device
│   └── myenv – Stacks – mystack      ← Stack device
│       ├── switch  (primary — no suffix)
│       ├── sensor.Status
│       ├── sensor.Containers
│       └── button.Restart
├── myenv – Networks  (if enabled)          ← Group device
│   └── sensor.bridge                  ← one entity per network (no sub-devices)
├── myenv – Volumes  (if enabled)           ← Group device
│   └── sensor.myvolume                ← one entity per volume (no sub-devices)
└── myenv – Images  (if enabled)            ← Group device
    └── sensor.nginx                   ← one entity per image (no sub-devices)

sensor.CPU usage, sensor.Memory usage, sensor.Containers  ← on env device
binary_sensor.Online
button.Check for updates               ← if container updates enabled

Dockhand – Schedules  (if enabled)         ← Global hub device (not env-specific)
└── Dockhand – Schedules – nightly-backup ← per-schedule device
    ├── sensor.Next run
    └── sensor.Last status
```

**Entity ID convention:** `<platform>.<env>_<type>_<name>_<attribute>` — for example `sensor.myenv_containers_mycontainer_state` or `switch.myenv_stacks_mystack`. The type segment (`containers`, `stacks`, `images`, etc.) makes entity_ids unambiguous even when a container and stack share the same name.

Each device in the list shows its **Type** (`model` field), so it's easy to distinguish containers from stacks, and group devices from individual ones. Every device also has a direct **open in Dockhand** link that takes you straight to the corresponding page.

Container and stack switches are **primary entities** — the entity name equals the device name with no suffix, following HA convention for the principal on/off control of a device.

### Portainer users
If you're also running the Portainer integration, note that this integration uses the same structural patterns — one environment device, child devices for containers and stacks, a control switch and `Restart` button per container and stack.

---

## Entities reference

### Environment (always on, 60 s)
| Entity | Type | Notes |
|---|---|---|
| Online | binary_sensor | Connectivity device class |
| CPU usage | sensor | % |
| Memory usage | sensor | %, with used/total bytes attributes |
| Containers running | sensor | with total/stopped/unhealthy attributes |
| Images | sensor | count of Docker images on the environment |

### Container (always on, 60 s)
| Entity | Type | Notes |
|---|---|---|
| State | sensor | running / exited / paused / etc. |
| Health | sensor | healthy / unhealthy / starting. Only created for containers with a Docker healthcheck configured — enabled by default |
| Container | switch | turn on = start, turn off = stop |
| Restart | button | restarts running container (use Container to start stopped) |
| Update | update | Shows when a newer image digest is available. Install triggers a pull-and-recreate via Dockhand's `batch-update` API. Note: vulnerability scanning is not applied by this API endpoint — a warning is shown in the entity when scanning is enabled on the environment. Disabled for system containers and containers with `dockhand.update=false` label. **Optional — enable via Configure** |

The following **diagnostic sensors** are also created for every container but are **disabled by default**. Enable the ones you want individually in **Settings → Entities**. They show as unavailable when the container is stopped or exited.

| Entity | Type | Unit | Notes |
|---|---|---|---|
| CPU usage | sensor | % | Percentage of total host CPU capacity |
| Memory usage | sensor | bytes (displayed in MiB) | Effective memory in use; page cache excluded. Includes `memory_cache_bytes` state attribute |
| Memory usage % | sensor | % | Memory used relative to configured limit (or host RAM if no limit is set) |
| Memory limit | sensor | bytes (displayed in MiB) | Configured container memory limit, or host RAM when unconstrained |
| Network in | sensor | bytes (displayed in MiB) | Cumulative bytes received; resets to 0 on container restart |
| Network out | sensor | bytes (displayed in MiB) | Cumulative bytes transmitted; resets to 0 on container restart |
| Disk read | sensor | bytes (displayed in MiB) | Cumulative block I/O reads; resets to 0 on container restart |
| Disk write | sensor | bytes (displayed in MiB) | Cumulative block I/O writes; resets to 0 on container restart |

### Stack (always on, 60 s)
| Entity | Type | Notes |
|---|---|---|
| Status | sensor | running / partial / stopped |
| Stack | switch | turn on = start, turn off = stop |
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

Dockhand uses three polling coordinators with independent intervals:

**Fast coordinator** (default 60 s, configurable) fetches:
- Environment dashboard stats for all environments in a single API call (CPU, memory, container/stack/image/volume/network counts)
- Full container list with state, image, and label details
- Full stack list with status and container counts
- Container resource stats for all running containers per environment in a single bulk API call (`GET /api/containers/stats?env=N`) — one call per environment regardless of container count. Stopped, exited, or created containers are absent from this response; their stats sensors show unavailable until running again

**Slow coordinator** (default 600 s, configurable) fetches:
- Per-environment detailed data for optional features: Images, Networks, Volumes
- Global schedule list

**Update coordinator** (default 86400 s / 24 h, configurable) — only active when container update entities are enabled:
- Per-environment image update availability via `POST /api/containers/check-updates`, which performs real registry queries against each container's image source. Kept infrequent to avoid unnecessary load on the Docker host. Use the **Check for image updates** button on any environment device to trigger an immediate check on demand.

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
- Only the API token is stored in the HA config entry; no username or password is ever stored
- The Restart button only works on *running* containers/stacks
- Disable **Verify SSL certificate** only if using a self-signed certificate on the Dockhand server
- Containers with the `dockhand.hidden=true` label are filtered from Dockhand's API responses and will not appear in HA
- **To exclude a container or stack from HA entirely**, the cleanest approach is to add the `dockhand.hidden=true` Docker label — it is filtered at the Dockhand API level so those containers never appear in HA at all. If you want the container visible in Dockhand but not in HA, disable the device in HA instead: go to **Settings → Devices & Services → Dockhand**, find the device, and use the three-dot menu → **Disable**. Disabling a device disables all of its entities at once and survives integration reloads. To act on many devices at once, use the **Devices** tab filter to narrow the list (e.g. filter by integration = Dockhand), then select multiple rows and use the bulk action menu.

---

## Translations

The integration ships with machine-generated translations for German, Spanish, French, Italian, Norwegian, Dutch, Polish, Portuguese, Swedish, and Chinese (Simplified), alongside the primary English strings. Native speaker corrections and new language additions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## Attribution

This integration was developed by **[@raetha](https://github.com/raetha)** with design assistance and code generation by **[Claude](https://claude.ai)** (Anthropic).

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
