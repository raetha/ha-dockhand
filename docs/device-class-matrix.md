# Dockhand — Device & Entity Reference

This document describes every device type and entity exposed by the integration,
including HA platform, device class, state class, unit, and current behavior.

---

## Entity naming convention

Entity IDs follow the pattern: `<platform>.<env>_<type>_<name>_<attribute>`

where:
- `<env>` is slugified from the environment (host) name — a literal from Dockhand
- `<type>` is the resource type plural (`containers`, `stacks`, `images`, `networks`, `volumes`)
- `<name>` is slugified from the resource name — a literal from Dockhand
- `<attribute>` is the entity attribute (`state`, `health`, `status`, `next_run`, etc.). Primary entities (switch, update) have no attribute suffix — their entity ID ends at `<name>`.

Examples:
- `sensor.myenv_containers_mycontainer_state`
- `switch.myenv_containers_mycontainer` (primary switch — no attribute suffix)
- `update.myenv_containers_mycontainer` (update entity — no attribute suffix)
- `sensor.myenv_stacks_mystack_status`
- `sensor.myenv_images_nginx`
- `sensor.dockhand_schedules_nightly_backup_next_run`

Environment-level entities omit the type and name segments:
- `sensor.myenv_cpu_usage`
- `binary_sensor.myenv_online`

---

## Device hierarchy

```
<env>                                         model: Environment
├── <env> – Containers                        model: Environment  (only if freestanding containers exist)
│   └── <env> – Containers – <name>          model: Container
├── <env> – Stacks                            model: Environment  (only if stacks exist)
│   └── <env> – Stacks – <stack>             model: Stack
│       └── <env> – Containers – <name>      model: Container    (Compose-managed)
├── <env> – Networks                          model: Environment  (optional, if enabled)
├── <env> – Images                            model: Environment  (optional, if enabled)
└── <env> – Volumes                           model: Environment  (optional, if enabled)

Dockhand – Schedules                          model: Service      (optional, if enabled)
└── Dockhand – Schedules – <task name>       model: Schedule
```

Notes:
- All devices use `manufacturer="Dockhand"` and ` – ` (U+2013 en-dash) as separator. En-dash is used because Docker forbids it in resource names, making it unambiguous as a separator even when names contain hyphens.
- The Containers group device is only created when at least one freestanding (non-Compose) container exists.
- Compose-managed containers are parented directly to their Stack device, not the Containers group.
- Network, image, and volume entities live directly under their group device — no individual sub-devices.
- Device identifiers use stable name-based keys so devices persist across container recreation and image updates.
- Schedule devices are named `"Dockhand – Schedules – {task name}"` so all schedules group together in the HA device list regardless of which environment they apply to.

---

## Polling coordinators

| Coordinator | Default interval | Data fetched |
|---|---|---|
| Fast | 60 s | Dashboard stats, containers, stacks |
| Slow | 600 s | Images, volumes, networks, schedules |
| Update | 86400 s | Container image update availability (optional) |

All intervals are configurable per installation.

---

## Environment device

Parent: none (root device). Entity ID prefix: `<platform>.{env}`

| Entity | Platform | Device class | State class | Unit | Enabled | Notes |
|---|---|---|---|---|---|---|
| Online | binary_sensor | connectivity | — | — | ✓ | True when environment responds |
| CPU usage | sensor | — | measurement | % | ✓ | |
| Memory usage | sensor | — | measurement | % | ✓ | Attributes: memory_used_bytes, memory_total_bytes |
| Containers | sensor | — | measurement | — | ✓ | Total count. Attributes: running, stopped, paused, restarting, unhealthy, pending_updates |
| Stacks | sensor | — | measurement | — | ✓ | Total count. Attributes: running, partial, stopped |
| Images | sensor | — | measurement | — | ✓ | Total count. Attributes: total_size_bytes |
| Volumes | sensor | — | measurement | — | ✓ | Total count. Attributes: total_size_bytes |
| Networks | sensor | — | measurement | — | ✓ | Total count |
| Containers disk usage | sensor | data_size | measurement | B | — | |
| Build cache size | sensor | data_size | measurement | B | — | |
| Activity events | sensor | — | measurement | — | — | Total event count. Attributes: today |
| Hawser agent version | sensor | — | — | — | — | Slow coordinator. Attributes: agent_name, agent_id, last_seen |
| Activity logging | binary_sensor | — | — | — | — | Whether event collection is enabled |
| Metrics collection | binary_sensor | — | — | — | — | Whether CPU/memory metrics are collected |
| Vulnerability scanning | binary_sensor | — | — | — | — | Whether image scanning is enabled |
| Update checks | binary_sensor | — | — | — | — | Whether auto-update checks are enabled |
| Auto update | binary_sensor | — | — | — | — | Whether auto-update deployment is enabled |
| Image pruning | binary_sensor | — | — | — | — | Slow coordinator. Whether scheduled image pruning is enabled |
| Check for updates | button | — | — | — | ✓ | Triggers immediate update check. Only present when updates are enabled |

---

## Container device

Parent: `<env> – Containers` group (freestanding), or `<env> – Stacks – <stack>` (Compose-managed)
Entity ID prefix: `<platform>.{env}_containers_{name}`

| Entity | Platform | Device class | State class | Unit | Enabled | Notes |
|---|---|---|---|---|---|---|
| *(primary — no attribute)* | switch | — | — | — | ✓ | on = start, off = stop. Reflects actual container state. Entity name = device name (HA primary-entity convention) |
| State | sensor | — | — | — | ✓ | running / exited / paused / restarting / dead. Attributes: status, image, restart_count, networks |
| Health | sensor | — | — | — | ✓ | Only created when container has a Docker healthcheck. healthy / unhealthy / starting |
| Restart | button | — | — | — | ✓ | |
| *(primary — no attribute)* | update | — | — | — | ✓ | Only present when updates are enabled. Install triggers batch-update API. No attribute suffix — follows HA convention for devices with a single update entity |

---

## Stack device

Parent: `<env> – Stacks` group device. Entity ID prefix: `<platform>.{env}_stacks_{name}`

| Entity | Platform | Device class | State class | Unit | Enabled | Notes |
|---|---|---|---|---|---|---|
| *(primary — no attribute)* | switch | — | — | — | ✓ | on = start, off = stop. Reflects actual stack status. Entity name = device name |
| Status | sensor | — | — | — | ✓ | running / partial / stopped. Attributes: container_count |
| Containers | sensor | — | measurement | — | ✓ | Count of containers in the stack |
| Restart | button | — | — | — | ✓ | |

---

## Image entities

Parent: `<env> – Images` group device. Optional — enable in setup.
One entity per image, no individual image sub-devices.
Entity ID prefix: `sensor.{env}_images_{repo}`

| Entity | Platform | Device class | State class | Unit | Notes |
|---|---|---|---|---|---|
| *repo-name* | sensor | — | — | — | Name is repository (e.g. `nginx`), state is tag (e.g. `latest`). Attributes: tags, digests, size_bytes, created, containers_using, plus OCI labels if present |

---

## Network entities

Parent: `<env> – Networks` group device. Optional — enable in setup.
One entity per network, no individual network sub-devices.
Entity ID prefix: `sensor.{env}_networks_{name}`

| Entity | Platform | Device class | State class | Unit | Notes |
|---|---|---|---|---|---|
| *network-name* | sensor | — | measurement | containers | Count of connected containers. Attributes: driver, scope, internal, subnet, connected_containers |

---

## Volume entities

Parent: `<env> – Volumes` group device. Optional — enable in setup.
One entity per volume, no individual volume sub-devices.
Entity ID prefix: `sensor.{env}_volumes_{name}`

| Entity | Platform | Device class | State class | Unit | Notes |
|---|---|---|---|---|---|
| *volume-name* | sensor | — | measurement | containers | Count of containers using the volume (0 = unused/dangling). Attributes: in_use, containers, driver, scope, mountpoint, labels, created |

---

## Schedule device

Parent: `Dockhand – Schedules` hub device. Optional — enable in setup.
Entity ID prefix: `sensor.dockhand_schedules_{task_name}`

| Entity | Platform | Device class | State class | Unit | Enabled | Notes |
|---|---|---|---|---|---|---|
| Next run | sensor | timestamp | — | — | ✓ | Attributes: cron_expression, enabled, environment, schedule_type |
| Last status | sensor | — | — | — | ✓ | Attributes: triggered_by, triggered_at, duration_ms, error_message, updates_found |

---

## Design notes

- **Enabled** column: ✓ = on by default, — = disabled by default (user must enable in HA entity settings).
- CPU and memory sensors have no HA device class because no standard class exists for these metrics.
- `State` and `Status` sensors use no device class (not `enum`) because values are plain strings from Docker and may expand in future API versions.
- Container and stack switches are stateful — `is_on` reflects the actual current state from the coordinator.
- `Restart` buttons are HA `button` entities (one-shot momentary actions, no on/off state).
- Volume and network sensors use MEASUREMENT state class; image sensors use none (tag strings are not numeric).
- `dockhand.hidden=true` containers are filtered by Dockhand's API and will not appear in HA.
- Primary switch entities (container and stack) have no attribute suffix in their entity_id — the entity name equals the device name, following HA convention for the principal on/off entity of a device.
