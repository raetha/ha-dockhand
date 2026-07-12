# Design: in-place container property updates (`update-runtime`)

Status: **implemented** in 1.8.0. Behind `CONF_ENABLE_RUNTIME_CONTROLS`
(default off) — see "Open questions" below for how each was resolved and
"Implementation notes" for what actually shipped vs. this original design.

## What Dockhand exposes

`POST /api/containers/{id}/update-runtime?env={env_id}` (added Dockhand
v1.0.33) applies a subset of Docker's `ContainerUpdate` call — the
properties Docker can change **without recreating the container**:

- `RestartPolicy`
- CPU: `CpuShares`, `CpuPeriod`, `CpuQuota`, `CpuRealtimePeriod`,
  `CpuRealtimeRuntime`, `CpusetCpus`, `CpusetMems`, `NanoCpus`
- Memory: `Memory`, `MemorySwap`, `MemoryReservation`, `MemorySwappiness`,
  `KernelMemory`
- Block I/O: `BlkioWeight`, `BlkioWeightDevice`, `BlkioDeviceReadBps`,
  `BlkioDeviceWriteBps`, `BlkioDeviceReadIOps`, `BlkioDeviceWriteIOps`
- `PidsLimit`

Body must contain only fields from this set; Dockhand silently drops
anything else server-side. Response is `{ success: true, warnings: [] }`
or `{ error, supportedFields }` on a malformed/empty request.

## Why this is worth doing

Today the only way to change a container's resource limits through the
integration is start/stop/restart via the recreate-based update flow —
nothing lets HA nudge CPU/memory limits live. A `number` entity for memory
limit (and maybe CPU quota) that applies instantly, no restart, is a real
differentiator versus the Portainer integration, which has no equivalent.

## Why scope must be restricted to stack-less containers only

Compose-managed containers (anything with a `com.docker.compose.project`
label — see `helpers._compose_project`) have their resource limits defined
in the compose file. A redeploy — especially a **git stack** redeploy
triggered by webhook/auto-sync, which can happen without the user directly
initiating it in HA — recreates the container from that file and silently
discards any in-place change we made. A user who set a memory limit from
HA would see it quietly reverted on the next sync with no indication why,
which is a worse experience than not offering the control at all.

**Decision: only create these entities for containers where
`_compose_project(container) is None`** (freestanding/stack-less). This
mirrors the same freestanding-vs-compose distinction `helpers.py` already
uses elsewhere (`has_freestanding`, diagnostics compose/freestanding
counts) — no new detection logic needed, just gate entity creation on it.

## Entity surface (as shipped)

All `entity_category = EntityCategory.CONFIG`, all
`entity_registry_enabled_default = False` (advanced/opt-in, like our other
low-level controls). Only created for stack-less, non-system containers,
only when `CONF_ENABLE_RUNTIME_CONTROLS` is enabled. The system-container
exclusion (Dockhand's own management container, or a Hawser agent) was
added after the initial implementation shipped, for the same reason the
running switch/restart button exclude them — an over-tight memory limit
could OOM-kill Dockhand itself, and changing restart policy could prevent
it recovering from a crash. See `_stack_has_system_container`'s sibling
check (plain `container.get("systemContainer")`, no stack involved here)
in `number.py`/`select.py`'s `async_setup_entry`, and the matching
`runtime_control_uids` guard in `__init__.py`'s central cleanup system.

| Entity | Type | Maps to | Notes |
|---|---|---|---|
| Memory limit | `number` | `Memory` (bytes) | Native unit bytes, `suggested_unit_of_measurement` MiB. `0` = unlimited (Docker's own convention). Has the auto-revert safety check on a decrease — see below. |
| CPU limit | `number` | `NanoCpus` | Shown as "CPUs" (e.g. 1.5), converted to nanocpus (`value * 1e9`) at the API boundary. `0` = unlimited. Max defaults to the environment's host CPU count (from `/api/host`), falling back to 64 if unknown. |
| Restart policy | `select` | `RestartPolicy.Name` | Options: `no`, `always`, `unless-stopped`, `on-failure`. Only `Name` is sent — no `MaximumRetryCount`. |
| Process limit | `number` | `PidsLimit` | `-1` = unlimited — Docker's own sentinel for this field, confirmed against `docker run --pids-limit -1` / `docker inspect` before implementation. |

Block I/O fields (`Blkio*`) are left out of this first pass — lower value
for a home-lab audience, and real added complexity (per-device weight
maps, not scalars).

## Open questions — resolved

1. **Warnings surfacing**: repair issue (`runtime_update_warning`), one per
   `(env, container, field)` so a repeat warning on the same field updates
   the same issue rather than piling up duplicates.
2. **Read-back**: optimistic. `async_set_native_value`/`async_select_option`
   update the entity's displayed value immediately; `_handle_coordinator_update`
   clears the optimistic value on the next slow poll (600s) regardless of
   outcome, so a value that didn't actually stick corrects itself within one
   cycle rather than lying indefinitely.
3. **Pids limit "unlimited"**: `-1`, matching Docker's own convention exactly
   (confirmed via Dockhand's own source: `pidsLimit: hostConfig.PidsLimit`,
   which is Docker's raw `HostConfig.PidsLimit` field).
4. **Memory below current usage**: confirmed this is not validated or
   rejected by Docker at all — the kernel enforces the new cgroup limit
   immediately, which can OOM-kill the container's processes right away.
   Docker gives no advance warning for this case, so there's no "warnings"
   entry from Dockhand to relay either.

   Mitigation shipped: on a **decrease** only (not an increase, not a set to
   `0`/unlimited), the Memory number entity schedules a one-time delayed
   check (`_MEMORY_SAFETY_CHECK_DELAY_SECONDS = 15`) via `async_call_later`.
   If the container is no longer `running` when that check fires, we
   auto-revert `Memory` to its previous value and raise a repair issue
   (`runtime_memory_reverted`) explaining what happened. This is a single
   bounded attempt tied to that one `set_native_value` call, not a general
   watchdog — it doesn't re-check repeatedly, and doesn't touch CPU/pids
   (neither has an OOM-kill-style failure mode).

## Implementation notes (vs. this original design)

- **Current-value source**: not covered in the original design — the
  containers list endpoint (`/api/containers`) doesn't expose current
  `Memory`/`NanoCpus`/`PidsLimit`/`RestartPolicy`, only
  `GET /api/containers/{id}/inspect` does. This is a genuine per-container
  API cost (one inspect call per stack-less container per slow-poll cycle),
  which is why the whole feature is gated behind `CONF_ENABLE_RUNTIME_CONTROLS`
  rather than being always-on like other `entity_registry_enabled_default
  = False` entities. Fetched on the slow (600s) coordinator, not the fast
  one — these values change rarely.
- **Our own update flow discards these settings too**: not just Compose/
  git-stack redeploys — recreating a container via our own `update`
  platform (batch-update-stream) also wipes any live cgroup tweak made
  here, the same way any Docker recreate does. This is expected and not
  specific to Dockhand's stack-redeploy behavior; it's just what
  "recreate" means. Worth being aware of, not something to fix.

## Non-goals

- No support for Compose-managed containers, ever, for the reasons above.
  If a user wants this for a compose container, the answer is "edit the
  compose file," not "use HA to route around it."
- No Block I/O controls in this pass (see above).
