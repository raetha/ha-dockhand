# Devices and entities

How devices are grouped, every entity the integration creates, and Dockhand tags. [Back to the README](../README.md)

## Device model

The integration uses a **grouped device hierarchy** that keeps the device list manageable regardless of how many containers and stacks you have.

```
Dockhand (dockhand.example.com)             ← Dockhand device: the server itself, showing its version;
├── update                                    environments and the Schedules hub connect through it
├── select.Default vulnerability scanner  (configuration)
└── binary_sensor.Live updates  (diagnostic)

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
│       ├── button.Restart
│       └── (diagnostic, if container stats enabled; Dockhand 1.0.52+)
│           └── sensor.CPU usage / Memory usage / … ← stack totals
├── myenv – Networks  (if enabled)          ← Group device
│   └── sensor.bridge                  ← one entity per network (no sub-devices)
├── myenv – Volumes  (if enabled)           ← Group device
│   └── sensor.myvolume                ← one entity per volume (no sub-devices)
└── myenv – Images  (if enabled)            ← Group device
    └── sensor.nginx                   ← one entity per image (no sub-devices)

sensor.CPU usage, sensor.Memory usage, sensor.Containers  ← on env device
binary_sensor.Online
button.Check for image updates
button.Update all containers               ← if update entities enabled (unavailable while nothing's pending)

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


## Entities reference

### Dockhand
| Entity | Type | Notes |
|---|---|---|
| (the device's name) | update | Whether a newer Dockhand release exists, from Dockhand's own check (**Settings → About** in Dockhand), every 6 hours. Read only: update Dockhand from Dockhand. Needs an admin token when Dockhand's authentication is on, and Docker access to Dockhand's own container (a local socket or a direct connection; not when Dockhand reaches its hosts only through Hawser) unless Dockhand doesn't run in a container. Until the check works there's no entity; it appears by itself once it does. A check that fails now and then leaves it unavailable until the next; if it doesn't work when Home Assistant starts, the entity is removed rather than left unavailable. Where Dockhand runs in an environment it manages, its container's own update entity can show the same update, from the image's side |
| Default vulnerability scanner | select | Configuration: the scanner (`none`, `grype`, `trivy`, `both`) every environment without its own uses. Needs `settings: view` to appear and `settings: edit` to change |
| Event collection mode | select | Configuration: how Dockhand collects Docker's events, `stream` (as they happen; Dockhand's default) or `poll`. Live updates and the Docker event entities depend on it (see [Data Updates](data-updates.md)). Needs `settings: view` to appear and `settings: edit` to change |
| Event poll interval | select | Configuration: 30, 60, 120 or 300 seconds between polls. Available only in Poll mode, like Dockhand's own setting |
| Live updates | binary_sensor | Diagnostic, connectivity: whether Dockhand's live feed is connected. `in_use` is false while no environment sends events, when there's nothing to receive |

### Environment (always on, 60 s)
| Entity | Type | Notes |
|---|---|---|
| Online | binary_sensor | Connectivity device class. Attributes: `connection_host`/`connection_port` (the environment's configured Docker connection endpoint, from `/api/environments`), `labels` (the tags you've assigned to the environment in Dockhand) |
| Connection type | sensor | `socket` / `direct` / `hawser-standard` / `hawser-edge` — matches Dockhand's own connection-type indicator, including its icon per type |
| CPU usage | sensor | %, with `cpu_count` (logical CPU count, from `GET /api/host`) and `top_containers` (top 5 by CPU — name/CPU%/memory%; only populated when **Enable container and stack stats** is on) attributes |
| Memory usage | sensor | % |
| Memory used, Memory total | sensor | bytes (displayed in MiB) |
| Containers | sensor | every container in the environment |
| Running, Stopped, Paused, Restarting, Unhealthy containers | sensor | count of containers in each state |
| Stacks | sensor | every stack in the environment |
| Running, Partially running, Stopped stacks | sensor | count of stacks in each state |
| Pending updates | sensor | every container whose update entity is on |
| Installable updates | sensor | the containers **Update all** would update (system containers excluded) |
| System container updates | sensor | Dockhand's own container and Hawser agents with an update, which are never updated in bulk |
| Newer version tags | sensor | containers whose only update is a newer version tag (moving to it means changing the image tag) |
| Image count, Volume count, Network count | sensor | count of each on the environment |
| Update all | button | Updates every container in the environment with a pending update in one batch (pull, scan if configured, recreate) — matches Dockhand's own "Update all" button exactly. Named "Update all containers" (a static name; Dockhand's own button shows a live "(N)" count, but a changing friendly name on a persistent entity reads as confusing churn in HA's own history, so ours doesn't). "Pending update" considers both the cheap cached check and, if enabled, the precise digest check — a container flagged by either counts. System containers are excluded from the count and from the update, same as Dockhand's own button. Goes through the same queue as Install, so each container's update entity shows its progress. **Only exists while Enable update entities is on**, and is unavailable while nothing is pending, so automations and dashboards can rely on its entity ID — this is the one thing that toggle actually gates besides entity display, since leaving it available with update entities disabled would be a backdoor to triggering real updates from HA |
| Prune unused images, Prune stopped containers, Prune unused networks, Prune unused volumes | button | Disabled by default, since pruning deletes: check what an environment has before turning one on, especially volumes, which take their data with them. The same as `dockhand.prune` for one kind of resource. Images follow the environment's **Image prune mode** (dangling only, unless it's set to all). Home Assistant can't ask for confirmation on a button entity itself, so pressing **Press** in its dialog prunes at once; a dashboard card can ask first with `confirmation: true` in its tap action |

**Environment settings** (configuration entities), changing the environment's settings in Dockhand. Each appears only once the token can read that setting; changing one needs the permission in the table above (a token that can't gets Dockhand's "permission denied" and the setting stays as it was).

| Entity | Type | Notes |
|---|---|---|
| Activity collection, Metrics collection | switch | Whether Dockhand records container events and CPU/memory metrics for the environment |
| Update checks, Auto update | switch | The environment's scheduled update check, and whether it installs what it finds (unavailable while update checks are off) |
| Image pruning | switch | Scheduled removal of unused images |
| Image prune mode | select | `dangling` (untagged images only) or `all` (every unused image) |
| Vulnerability scanner | select | `none`, `grype`, `trivy` or `both`; the read-only **Vulnerability scanning** sensor says whether one is set |

The schedules themselves (when update checks and pruning run) stay in Dockhand.

The following are sourced from `GET /api/host` (already polled every slow cycle for the Hawser version sensor — no extra API call) but are **disabled by default**, since they're niche/diagnostic. Enable the ones you want in **Settings → Entities**.

| Entity | Type | Notes |
|---|---|---|
| Hawser agent version | sensor | Live-fetched from the agent for standard-mode Hawser connections. `agent_name`/`agent_id` attributes, filled in only for edge-mode connections (the only mode Dockhand records them for), sourced from `/api/environments` |
| Hawser last seen | sensor | Timestamp of the Hawser Edge agent's last check-in. Hawser Edge environments only. It changes every poll, so each poll adds a row to Home Assistant's database while it's on |
| Host platform | sensor | OS platform, e.g. `linux`, with an `architecture` attribute, e.g. `x64` |
| Docker version | sensor | Docker Engine server version |
| Host last boot | sensor | Timestamp, computed from host uptime; changes only when the host reboots |

Also disabled by default, but at no extra cost — the data's already part of the same `/api/dashboard/stats` call already polled every 60s:

| Entity | Type | Notes |
|---|---|---|
| Disk usage | sensor | Total bytes across images, volumes, containers, and build cache — matches Dockhand's own disk-usage breakdown |
| Images, Containers, Volumes, Build cache disk usage | sensor | Each part of Disk usage on its own |
| Pinned digest updates, Held updates | sensor | Containers whose only update is a moved digest on a pinned image, or one held for the minimum image age |

Also disabled by default, each sourced from its own gated API call — only fetched at all when the matching Dockhand setting is on for that environment, so an environment that doesn't use the feature never pays for the extra request:

| Entity | Type | Notes |
|---|---|---|
| Activity events | sensor | Total event count, with a `recent_events` list attribute (last 10, each with container name/action/timestamp). Only polled when **Activity collection** is on for the environment in Dockhand |
| Activity events today | sensor | Events recorded today |
| Vulnerabilities | sensor | Total finding count from Dockhand's own vulnerability scanner. Only polled when **Vulnerability scanning** is on for the environment in Dockhand |
| Critical, High, Medium, Low vulnerabilities | sensor | Findings of each severity |
| Scanned images | sensor | Images with at least one scan |

### Container (always on, 60 s)

The container's device shows its image's version where a physical device shows its firmware: the image's `org.opencontainers.image.version` label when it has one, otherwise its tag (`1.27`, `latest`). It follows the container onto a new image.

| Entity | Type | Notes |
|---|---|---|
| State | sensor | One of Docker's states: `created`, `running`, `paused`, `restarting`, `removing`, `exited` or `dead` (shown translated; anything else Docker might add later shows as unknown). Attributes include `image`, `networks`, `tags` (see [Tags](#tags)), `exit_code` while the container is exited, `restart_count` while it's restarting (Dockhand only counts restarts then), and `system_container` (`true` for Dockhand's own container and Hawser agents) |
| Health | sensor | `healthy`, `unhealthy` or `starting`. Only created for containers with a Docker healthcheck configured — enabled by default |
| Docker event | event | Fires when Docker reports the container starting, stopping, dying (with its `exit_code`), being killed, running out of memory, restarting, pausing, resuming, being updated, or its health check passing, failing or starting — for automations, like the Portainer integration's. Comes from the live feed (see [Data Updates](data-updates.md)), so it's unavailable for environments Dockhand doesn't send events for, and misses events while the feed is disconnected. Disabled by default |
| Container | switch | turn on = start (or resume, if paused), turn off = stop. **Not created for system containers** (Dockhand itself, or a Hawser agent) — see note below |
| Restart | button | restarts the container, or starts it if stopped. **Not created for system containers** — see note below |
| Pause, Resume | button | freeze a running container's processes, and let a paused one run again; each is unavailable outside the state it applies to. Disabled by default in the entity registry. **Not created for system containers** — see note below |
| Update | update | Created automatically for every container, as long as **Enable update entities** is on (default on; see Options above) — whether or not Dockhand's scheduled update check is turned on for the environment. Shows the image tag as `installed_version`, and flips `latest_version` to `update-pending` as soon as a Dockhand update check (scheduled or manual) finds one, with no registry query of its own. Enable **Enable precise update versions** in Configure to also show real image-digest version numbers via periodic registry queries. Install triggers a scanned pull-and-recreate via Dockhand's `batch-update-stream` API (works at either tier — it only needs the container ID), honoring the environment's configured vulnerability blocking policy, and reports live install progress. Installs that start together (Home Assistant's own "update all", the cards' Update all, a script updating several containers) wait two seconds for each other and go to Dockhand as one job, which updates the containers one after another; one started while a job is running joins the next job. Each entity still shows its own progress and its own result, and the environment's precise update check (if enabled) runs once afterwards rather than once per container. Disabled for system containers and containers with `dockhand.update=false` label. When Dockhand also finds a newer version tag (one you'd move to by changing the container's image tag, so Install can't apply it), it's shown as `latest_version` only while nothing installable is pending, and is always available in the `newer_version` attribute, with `newer_version_bump` (`major`/`minor`/`patch`) and `newer_versions_count` (how many newer versions there are, including that one) beside it. Two more cases Install can't apply, shown the way Dockhand's own containers list shows them: for an image pinned to a digest (`image:tag@sha256:…`) whose tag has moved on (Dockhand 1.0.54+), the entity turns on with Install unavailable and `pinned_digest_moved: true`, since the pin has to be changed; and an update Dockhand is holding until the new image reaches its minimum image age (Dockhand 1.0.52+) turns it on with Install unavailable too, with `update_held_hours` counting down the hours left (0 once the wait is over, until Dockhand's next update check offers it as a normal update). Both turn off again as soon as Dockhand stops reporting them |
| Memory limit, CPU limit, Process limit | number | Live in-place resource limits (0 = unlimited, except Process limit where -1 = unlimited, matching Docker's own convention). Stack-less (non-Compose) containers only. **Optional — Enable runtime controls in Configure**, which creates them enabled. **Not created for system containers** — see note below |
| Restart policy | select | Live restart policy (`no`/`always`/`unless-stopped`/`on-failure`). Stack-less containers only. **Optional — Enable runtime controls in Configure**, which creates them enabled. **Not created for system containers** — see note below |
| Auto update | switch | Toggles Dockhand's own scheduled auto-update check for this container (distinct from the Update entity above, which is manual/HA-triggered). Persisted by container name, survives recreation. Not gated behind Configure — always available, disabled by default in the entity registry. **Not created for system containers** — see note below |

The following **diagnostic sensors** are created for every container while **Enable container and stack stats** is on (see Options above). They show as unavailable when the container is stopped or exited.

| Entity | Type | Unit | Notes |
|---|---|---|---|
| CPU usage | sensor | % | Percentage of total host CPU capacity |
| Memory usage | sensor | bytes (displayed in MiB) | Effective memory in use; page cache excluded |
| Memory cache | sensor | bytes (displayed in MiB) | Page cache, left out of Memory usage |
| Memory usage % | sensor | % | Memory used relative to configured limit (or host RAM if no limit is set) |
| Memory limit | sensor | bytes (displayed in MiB) | Configured container memory limit, or host RAM when unconstrained |
| Network in | sensor | bytes (displayed in MiB) | Cumulative bytes received; resets to 0 on container restart |
| Network out | sensor | bytes (displayed in MiB) | Cumulative bytes transmitted; resets to 0 on container restart |
| Disk read | sensor | bytes (displayed in MiB) | Cumulative block I/O reads; resets to 0 on container restart |
| Disk write | sensor | bytes (displayed in MiB) | Cumulative block I/O writes; resets to 0 on container restart |

### Stack (always on, 60 s)
| Entity | Type | Notes |
|---|---|---|
| Status | sensor | One of `running`, `partial`, `restarting`, `stopped` or `created` (shown translated; anything else shows as unknown). `system_container` is `true` when the stack holds Dockhand's own container or a Hawser agent. The stack device's `model` (Internal Stack / Git Stack / Untracked Stack) shows why a stack does or doesn't have the git-stack entities below. Carries the stack's `tags` and `tag_colors` (see [Tags](#tags)). "Untracked" matches Dockhand's own terminology for a stack it discovered but never created/adopted/git-tracked through its own UI |
| Stack | switch | turn on = start, turn off = stop. **Not created for a stack containing a system container** — see note below |
| Restart | button | restarts the stack, or starts it if stopped. **Not created for a stack containing a system container** — see note below |
| Redeploy | button | pulls the latest image for each service and redeploys — matches Dockhand's own Redeploy popover exactly, including its own literal button title, with its default checkboxes (Pull images checked, Build images and Force recreate unchecked), so it behaves the same as clicking Redeploy in Dockhand's own UI without touching any options. Only recreates containers whose config actually changed (e.g. a new image digest) — doesn't force-recreate everything. **Internal stacks only** — git stacks have their own Deploy/Sync from Git button (below) with different mechanics; not created for Untracked stacks (no compose file location for Dockhand to redeploy from) or for a stack containing a system container |
| Updates available | binary_sensor | on when any container in the stack has a pending image update. Requires Dockhand 1.0.37+ — automatically not created on older versions, since this data isn't in the API response at all until then |
| Pending updates | sensor | How many of the stack's containers have an update, as Dockhand counts them. Created with Updates available |
| CPU usage, Memory usage, Memory limit, Network in, Network out, Disk read, Disk write, Running containers | sensor | Diagnostic. The stack's totals exactly as Dockhand reports them (`GET /api/stack-stats`, the same numbers its own Stacks page shows): everything summed over the stack's running containers except Memory limit, which is the largest single container limit. No memory percentage, since Dockhand doesn't report one for a stack. **Requires Dockhand 1.0.52+** — not created on older versions — and only created while **Enable container and stack stats** is on. Unavailable while none of the stack's containers is running |

> **System containers.** Dockhand classifies its own management container and any Hawser remote agent as "system containers" — Dockhand's own UI hides start/stop/restart for these (and for any stack containing one), since taking them down can break Dockhand's ability to manage the host at all. Dockhand's API itself doesn't enforce this — only its UI does — so this integration enforces it independently: the Container/Stack switch, Restart button, container Auto update switch, and runtime controls (memory/CPU/process limits, restart policy) simply aren't created for a system container or a stack that contains one. Read-only entities (State, Health, resource sensors) are unaffected. A system container's Update entity still reports when a new image is available, but Dockhand's own scheduled update check skips system containers, so that is only detected by the environment's **Check for image updates** button (or by **Enable precise update versions**, which runs that same check on its own schedule). A result from the button is kept until the container is recreated or the next check, but not across a Home Assistant restart.

> **Updates for Dockhand and Hawser themselves depend on their image tag.** Dockhand only reports a newer image for its own container or a Hawser agent when the image's tag has moved on — so with a floating tag (`latest`, or a major-version tag) every new release shows up on that container's Update entity once **Enable precise update versions** runs, or after **Check for image updates**. With a pinned version tag (`v1.0.53`, `0.2.50`) the tag never moves, and Dockhand never offers a newer version tag for a system container (it hides those from its own containers list too), so nothing is reported through the containers API. For Dockhand only, the integration fills that gap from Dockhand's own release check (the one behind its "update available" notice), which names the newest release: the Update entity on Dockhand's own container turns on with that version as `latest_version` and `newer_version`, Install unavailable. That check needs **Enable precise update versions**, an admin API token, and Dockhand able to inspect its own container — through its own Docker socket or an environment with a socket or direct connection that lists it. When Dockhand only reaches its hosts through Hawser it can't, so the check isn't made. Hawser has no equivalent check anywhere in Dockhand: **for reliable update notifications for Dockhand and Hawser, run them on a floating tag.**

The following are created automatically whenever a stack is detected as **git-tracked** — no config option needed (it's one bulk API call per environment, not per-stack).

| Entity | Type | Notes |
|---|---|---|
| Sync status | sensor | `pending`/`syncing`/`synced`/`error`. Attributes include last commit, sync error, auto-deploy, and webhook-enabled |
| Last sync | sensor | Timestamp of the last git sync |
| Sync error | binary_sensor | On when the last sync/deploy attempt failed |
| Deploy / Sync from Git | button | Same underlying action either way (sync from git, then redeploy) — the name and icon change based on the stack's current status to match Dockhand's own labeling exactly: **"Deploy"** (rocket icon) while the stack is down (not yet deployed, or created but not started), **"Sync from Git"** (refresh icon) once it's up. Unlike the internal-stack Redeploy button above, this does **not** guarantee a fresh image pull or a forced recreate: whether containers actually get recreated depends on whether the git sync found real changes, and whether images get re-pulled depends on this git stack's own "repull images" setting in Dockhand (not something this integration can override per-press) — a Dockhand API limitation, not a choice made here. There's no separate check-only Sync button — Dockhand's own `deployGitStack()` always runs the identical sync step first regardless of whether a deploy follows, confirmed from source, so a standalone check-only action would add no real capability. *Dockhand's own terminology/iconography here may change in a future version; if you notice this drift from what Dockhand itself calls it, that's worth flagging.* |
| Auto deploy | switch | Toggles the stack's own scheduled sync+redeploy job. Disabled by default in the entity registry |

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

Each schedule gets its own device under the **Schedules** hub (or its environment's Schedules group).

| Entity | Type | Notes |
|---|---|---|
| Next run | sensor | TIMESTAMP device class; suitable for time-based automation triggers. Attributes include cron expression, enabled state, environment name, and schedule type |
| Last status | sensor | DIAGNOSTIC; one of Dockhand's results: `queued`, `running`, `success`, `failed`, `skipped`, `warning`, `error`, `cancelled` or `stale` (shown translated, with `schedule_type` too) — use a `state` trigger for clean failure-alert automations. Attributes include triggered_by, triggered_at, duration_ms, error_message |
| Run now | button | runs the schedule once now, outside its timing. Not created for scheduled reports and stack deploys, which Dockhand can't run on demand |
| Enabled | switch | off pauses the schedule, as in Dockhand. Only for the schedules Dockhand can pause from here: scheduled container start/stop (one switch covers a container's start and stop together), environment update checks, image prunes, backups, and the built-in schedule, event, scanner and scan-retention cleanups. A container's auto-update and a git stack's auto-sync are paused with the **Auto update** and **Auto deploy** switches on the container or stack instead |


## Tags

Dockhand 1.0.49+ lets you tag containers and stacks with short coloured labels (`media`, `critical`, `auth`…), assigned in Dockhand or named in a container's `dockhand.tags` label (`dockhand.tags=media,critical:red`). The container State sensor and the stack Status sensor carry them as `tags` (a list of names) and `tag_colors` (each name's colour, as Dockhand draws it), so an automation can act on a tag:

```yaml
triggers:
  - trigger: state
    entity_id: sensor.web_state
    to: exited
conditions:
  - "{{ 'critical' in state_attr('sensor.web_state', 'tags') }}"
```

They show the tags Dockhand's own lists show. A container's tags don't include its stack's, which Dockhand only adds when you turn that on in its containers list. Tags are read every 10 minutes (labels with every poll), so a new tag can take that long to appear.
