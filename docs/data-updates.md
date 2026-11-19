# Data updates

How and when data refreshes, the live feed, and refreshing on your own schedule. [Back to the README](../README.md)

Dockhand uses four polling coordinators, each on a fixed schedule, and a live feed of changes on top of them:

**Fast coordinator** (every minute) fetches:
- Environment dashboard stats for all environments in a single API call (CPU, memory, container/stack/image/volume/network counts, whether update-check is enabled)
- Full container list with state, image, and label details
- Full stack list with status and container counts
- Container resource stats for all running containers per environment in a single bulk API call (`GET /api/containers/stats?env=N`) — one call per environment regardless of container count. Stopped, exited, or created containers are absent from this response; their stats sensors show unavailable until running again
- A cheap, no-registry-query check of Dockhand's own cached pending-update flags, for every environment — this is what powers the `update-pending` status on update entities

**Slow coordinator** (every 10 minutes) fetches:
- Per-environment detailed data for optional features: Images, Networks, Volumes, runtime controls
- Git stack sync status, host info (platform/arch/Docker version/uptime), and container auto-update settings — always fetched, no config option needed, since these are single cheap bulk calls per environment
- Global schedule list. While any schedule run is queued or running (started from Home Assistant or by Dockhand), just the schedules are fetched again every 10 seconds until it ends; Dockhand's live feed doesn't carry schedule runs
- A handful of fields with no other source (image-prune enabled, Hawser agent identity, configured connection host/port)

**Update coordinator** (once a day) — only active when **Enable precise update versions** is turned on. Update entities themselves exist for every container as long as **Enable update entities** is on (default on), and this coordinator is purely additive for them — it only upgrades their version display from an image tag to a precise digest, never gates whether they exist. It has nothing to do with the env-level **Check for image updates** button's own existence — that button always exists and always calls Dockhand's real check-updates API directly, whether or not this coordinator is running; if this coordinator *is* running, the button's result also updates it:
- Per-environment image update availability via `POST /api/containers/check-updates`, which performs real registry queries against each container's image source. Kept infrequent to avoid unnecessary load on the Docker host. The **Check for image updates** button on every environment device (always present, regardless of any option) triggers an immediate check on demand — and, if **Enable update entities** is on, its result also refreshes the cheap Tier 1 status immediately rather than waiting for the next 60-second poll.

**Version coordinator** (every 6 hours) reads Dockhand's own version for the Dockhand device, from its changelog (the only place Dockhand reports it), and runs Dockhand's own update check for its update entity. It's also read again whenever the live feed reconnects, which is when an upgraded Dockhand comes back.

Entities update automatically when their coordinator refreshes. If a whole poll fails (Dockhand unreachable, say), that coordinator's entities become unavailable until the next successful one; the failure is logged once, and so is the recovery. If only part of a poll fails — one environment, or one optional fetch — only the entities that depend on that part become unavailable, and devices are never removed because of a failed fetch. All three coordinators handle token errors transparently — a 401 response surfaces a re-authentication notification in HA rather than silently retrying.

**Live updates.** Dockhand watches Docker's events for every environment that collects activity or metrics (both are environment settings in Dockhand; metrics are on by default), and Hawser Edge agents always send theirs. While at least one environment does, the integration keeps Dockhand's activity feed open, and a change there (a container stopping, starting, turning unhealthy, being recreated) refreshes that environment's containers and stacks within a couple of seconds, instead of at the next poll. An environment going offline or coming back triggers a full refresh. The feed only speeds things up: polling carries on as before and catches anything missed. If the connection drops (Dockhand restarting, its host losing power), it's retried after 5 seconds, backing off to 5 minutes, and everything is refreshed once it's back. Without the `activity: view` permission, or with environments that collect neither, there's no feed and changes show on the next poll, so within a minute. The Dockhand device's **Live updates** sensor shows whether the feed is connected.

Leave Dockhand's **Settings → General → Activity event collection mode** on **Stream**, its default (the Dockhand device's **Event collection mode** shows it, and Home Assistant raises a repair while it's on Poll). In **Poll** mode Dockhand reads Docker's events only once per interval (60 seconds by default), so the live feed and the Docker event entities lag by up to that interval, and with an interval over 30 seconds some events never arrive: each poll reads only the last 30 seconds. Hawser Edge environments aren't affected; their agents send events themselves.

An action taken from Home Assistant (a switch, a button, Install) refreshes that environment straight away. Actions on many containers at once (one `switch.turn_off` on ten containers, say) share those refreshes rather than making one each.

### Controlling when data refreshes

Home Assistant doesn't let integrations offer a polling-interval setting; the intervals above are fixed. To refresh on your own schedule instead, turn polling off and call `homeassistant.update_entity` from an automation:

1. **Settings → Devices & services → Dockhand**, then the three-dot menu → **System options**, and turn off **Enable polling for changes**. This stops all four coordinators' schedules; actions still refresh what they change, and so does the live feed, which isn't polling.
2. Call `homeassistant.update_entity` with an entity from the coordinator you want refreshed. One entity refreshes that coordinator for every environment, so one per coordinator is enough:

| To refresh | Use any entity of this kind | For example |
|---|---|---|
| Fast coordinator | an environment's **Containers** sensor, or any container or stack entity | `sensor.local_containers` |
| Slow coordinator | an environment's **Docker version** sensor, or any image, volume, network, schedule or git stack entity | `sensor.local_docker_version` |
| Update coordinator | none: press an environment's **Check for image updates** button (`button.press`), which checks that environment only | `button.local_check_for_image_updates` |
| Version coordinator | none: it has no entities; Dockhand's version is read every 6 hours, when the live feed reconnects, and when the integration reloads | |

```yaml
automation:
  - alias: "Refresh Dockhand every 5 minutes"
    triggers:
      - trigger: time_pattern
        minutes: "/5"
    actions:
      - action: homeassistant.update_entity
        target:
          entity_id: sensor.local_containers
```

Entity IDs depend on your environment names; check yours under the environment's device. Refreshing more often than the defaults mainly adds load on Dockhand and the Docker hosts behind it, and the update check makes real registry queries for every container, so keep that one infrequent.
