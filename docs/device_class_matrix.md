# Dockhand — Device & Entity Reference

This document describes every device type and entity exposed by the integration,
including HA platform, device class, state class, unit, and current behavior.
It reflects the current architecture as of the dual-coordinator (fast/slow poll) model.

---

## Device hierarchy

```
<Environment name>                  model: Dockhand Environment
├── <Environment name> – Containers model: Dockhand Environment
│   └── <container name>            model: Docker Container
├── <Environment name> – Stacks     model: Dockhand Environment
│   └── <stack name>                model: Compose Stack
├── <Environment name> – Networks   model: Dockhand Environment  (if enabled)
│   └── <network name>              model: Docker Network
├── <Environment name> – Volumes    model: Dockhand Environment  (if enabled)
│   └── <volume name>               model: Docker Volume
└── <Environment name> – Images     model: Dockhand Environment  (if enabled)

Schedules                           model: Dockhand Environment  (if enabled)
└── <schedule name>                 model: Dockhand Schedule
```

All devices use `manufacturer="Dockhand"` consistently. All devices carry a `configuration_url` that deep-links directly to the
corresponding page in the Dockhand UI.

---

## Polling coordinators

| Coordinator | Default interval | Entities |
|---|---|---|
| Fast | 60 s | Environment stats, containers, stacks |
| Slow | 600 s | Images, volumes, networks, schedules |

Both intervals are configurable per installation.

---

## Environment device

Parent: none (root device)

| Entity | Platform | Device class | State class | Unit | Notes |
|---|---|---|---|---|---|
| Online | binary_sensor | connectivity | — | — | True when environment responds |
| CPU usage | sensor | — | measurement | % | Raw value × 100 from API |
| Memory usage | sensor | — | measurement | % | Attributes: used/total in bytes and GB |
| Containers running | sensor | — | measurement | — | Attributes: total, stopped, paused, unhealthy, pending_updates |

---

## Container device

Parent: `<Environment> – Containers` group device

| Entity | Platform | Device class | State class | Unit | Notes |
|---|---|---|---|---|---|
| State | sensor | — | — | — | running / exited / paused / restarting / dead |
| Health | sensor | — | — | — | healthy / unhealthy / starting / none (absent if no healthcheck) |
| Running | switch | — | — | — | `on` = start, `off` = stop. State reflects actual container state. |
| Restart | button | — | — | — | Calls `/restart`. Docker can only restart a *running* container — use Running switch to start stopped ones. |

---

## Stack device

Parent: `<Environment> – Stacks` group device

| Entity | Platform | Device class | State class | Unit | Notes |
|---|---|---|---|---|---|
| Status | sensor | — | — | — | running / partial / stopped |
| Running | switch | — | — | — | `on` = start, `off` = stop. Reflects actual stack status. |
| Restart | button | — | — | — | Calls `/restart`. Only works on running or partial stacks. |

---

## Image entity

Parent: `<Environment> – Images` group device. Optional — enable in setup.
One entity per image (no sub-devices). The entity name is the repository portion of the
primary tag (e.g. `cloudflare/cloudflared`) and the state is the tag portion (e.g. `latest`,
`2.1.0`). For untagged images the name is the short hash ID and the state is `None`.

| Entity | Platform | Device class | State class | Unit | Notes |
|---|---|---|---|---|---|
| *repo-name* | sensor | — | — | — | Named for the image repo (e.g. `nginx`); state is the tag (e.g. `latest`). Attributes: tags (list), digests (list), size_bytes, created, containers_using. |

---

## Network device

Parent: `<Environment> – Networks` group device. Optional — enable in setup.

| Entity | Platform | Device class | State class | Unit | Notes |
|---|---|---|---|---|---|
| Containers | sensor | — | measurement | — | Count of connected containers. Attributes: driver, scope, internal, subnet, connected_containers. |

---

## Volume device

Parent: `<Environment> – Volumes` group device. Optional — enable in setup.

| Entity | Platform | Device class | State class | Unit | Notes |
|---|---|---|---|---|---|
| Size | sensor | — | measurement | B | Bytes. Returns `unavailable` until Docker has run `docker system df`. Attributes: driver, mountpoint, scope, ref_count, size_gb, labels. |

---

## Schedule device

Parent: `Schedules` hub device. Optional — enable in setup. Read-only — no run-now action exists in the Dockhand API.

| Entity | Platform | Device class | State class | Unit | Notes |
|---|---|---|---|---|---|
| Next run | sensor | timestamp | — | — | ISO 8601 datetime, converted to UTC. Attributes: cron_expression, enabled, environment, schedule_type. |
| Last status | sensor | — | — | — | Status string from last execution. Attributes: triggered_by, triggered_at, duration_ms, error_message, updates_found. |

---

## Notes

- CPU and memory sensors have no HA device class because no standardised class exists for these metrics.
- Container `State` and stack `Status` sensors intentionally use no device class (not `enum`) because the
  values are plain strings returned by Docker/Dockhand and may expand in future API versions.
- `Running` switches on containers and stacks are stateful — `is_on` reflects the actual current state
  from the coordinator, not a locally-cached toggle.
- `Restart` buttons are modelled as HA `button` entities because they are one-shot momentary actions with
  no meaningful on/off state, which is semantically correct per the HA entity model.
- Volume sizes are reported in bytes (HA standard unit `B`) and HA will display them with appropriate
  unit scaling (KB, MB, GB) automatically.
