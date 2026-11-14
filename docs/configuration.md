# Configuration

Setup fields, options, authentication and the permissions a token needs. [Back to the README](../README.md)

## Configuration parameters

### Setup fields (entered once at install time)

| Field | Description | Default |
|---|---|---|
| **API URL** | Full URL to your Dockhand server, e.g. `http://dockhand.local:3000` | — |
| **Verify SSL certificate** | Validate the server's SSL/TLS certificate. Uncheck only if your Dockhand instance uses a self-signed certificate | on |
| **API Token** | A Dockhand API token starting with `dh_`. Only prompted if the server requires authentication. Generate one under **Profile → API tokens** | — |

### Options (adjustable via Configure)

The following can be changed at any time via the **Configure** button on the integration card, without removing the integration. Saving reloads the integration, so changes take effect at once. How often data refreshes isn't a setting: see [Data Updates](data-updates.md).

| Field | Description | Default |
|---|---|---|
| **Enable schedules** | Create entities for Dockhand scheduled tasks | off |
| **Enable images** | Create entities for Docker images on each host | off |
| **Enable volumes** | Create entities for Docker volumes on each host | off |
| **Enable networks** | Create entities for Docker networks on each host | off |
| **Enable update entities** | Create a Home Assistant `update` entity for every container, showing whether an image update is available. Turn this off if you manage updates another way and don't want Dockhand's containers appearing in HA's own update management (see [github.com/raetha/ha-dockhand/issues/23](https://github.com/raetha/ha-dockhand/issues/23)). Turning it off removes the env-level **Update all** button, since that would otherwise be a way to trigger real container updates from HA even with this off. **Check for image updates** and **Enable precise update versions** below keep working regardless — checking for updates is read-only, and it still refreshes Dockhand's own cached values that other things (e.g. the stack "updates available" sensor) use either way | on |
| **Enable precise update versions** | Update entities already exist for every container, showing an image tag and an `update-pending` status from Dockhand's own cached results — no extra API cost. This adds real registry queries once a day, upgrading those same entities to show precise version numbers (image digests) instead — but only while **Enable update entities** above is also on. It's also the only way updates to Dockhand itself and Hawser agents are found (see the notes at the end of [Stack](entities.md#stack-always-on-60-s)). The env-level **Check for image updates** button doesn't depend on this at all (it always exists and always triggers a real check); this only controls whether *that check's result* also updates the precise-version display | off |
| **Enable runtime controls** | Create `number`/`select` entities to change a stack-less container's memory limit, CPU limit, process limit, and restart policy live, without recreating it. Not available for Compose-managed containers. Costs one extra API call per stack-less container per slow poll | off |
| **Enable container and stack stats** | Create the per-container CPU, memory, network, and block I/O sensors, plus Dockhand's totals for each stack (Dockhand 1.0.52+) — not created at all until this is on, same as Images/Volumes/Networks below. Also gates the underlying stats API call itself, not just entity creation. Off since it's a lot of entities most people don't need | off |

Below these, three collapsed sections, **Environment entities**, **Container entities** and **Stack entities**, list the entities that are disabled by default (Pause and Resume, Docker event, disk usage, uptime and so on). Checking one turns it on for every environment, container or stack, including ones added later, except where you turned it off yourself. Unchecking it turns it off everywhere again, including any you turned on by hand. **All of these** checks or unchecks every type in a section at once. Vulnerabilities, Disk usage and Activity events also bring the sensors that break them down (each severity and scanned images, each part of disk usage, today's events).

### Reconfigure (change URL, SSL, or API token)

Use **Reconfigure** (three-dot menu → Reconfigure) to change the **API URL**, **Verify SSL** setting, or **API Token**. The token field is pre-populated and masked — clear it to disable authentication (you will be re-prompted if the server still requires it), or enter a new value to rotate credentials. The integration re-probes the server on save.


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

## Permissions

A token acts as the Dockhand user who created it. In Dockhand's free edition every signed-in user may do everything, so there's nothing to set up. With **Dockhand Enterprise** roles, the token's user needs these permissions (per environment, where the role is environment-scoped):

| For | Dockhand permission |
|---|---|
| Everything (environments, their stats and host details) | `environments: view` |
| Containers, stacks and their sensors (including their Dockhand tags) | `containers: view`, `stacks: view` |
| Images, volumes, networks (when enabled) | `images: view`, `volumes: view`, `networks: view` |
| Schedules and the Auto update switch's state | `schedules: view` |
| Activity sensor, live updates | `activity: view` |
| Container switch, Restart, Pause, Resume | `containers: start`, `stop`, `restart` |
| Stack switch, Restart, Redeploy, git stack Deploy | `stacks: start`, `stop`, `restart` |
| Install, Update all, runtime controls, `dockhand.recreate_container` | `containers: create` |
| Auto update and git stack Auto deploy switches | `schedules: edit`, `stacks: edit` |
| Environment settings (activity and metrics collection, update checks, pruning) | `environments: edit`; the vulnerability scanner: `settings: edit` |
| Schedule Run now / Enabled | `schedules: run` / `schedules: edit` (built-in cleanups: `settings: edit`; a container start/stop schedule also needs `containers: start` and `stop`) |
| `dockhand.prune`, Prune buttons | `remove` on each resource type pruned |
| Updates to Dockhand itself (precise update versions) | an administrator |

Anything the token can't read shows as unavailable (with a repair issue saying which data couldn't be fetched); an action it isn't allowed to take fails with a "doesn't have permission" error.

**Docker socket proxies.** If Dockhand itself reaches Docker through a socket proxy (such as `tecnativa/docker-socket-proxy`), the proxy decides what Dockhand can do, whatever the token allows. Dockhand's own documentation covers what it needs; for this integration's features, note that actions need write requests (`POST`) allowed for the resource involved (`CONTAINERS`, `IMAGES`, `VOLUMES`, `NETWORKS`), pruning and recreating need `DELETE` too where the proxy separates it, and disk-usage figures need `SYSTEM` (`/system/df`).


## Notes

- All data is fetched locally — no external cloud services
- Only the API token is stored in the HA config entry; no username or password is ever stored
- Disable **Verify SSL certificate** only if using a self-signed certificate on the Dockhand server
- **To exclude a container or stack from HA entirely**, the cleanest approach is to add the `dockhand.hidden=true` Docker label — it is filtered at the Dockhand API level so those containers never appear in HA at all. If you want the container visible in Dockhand but not in HA, disable the device in HA instead: go to **Settings → Devices & Services → Dockhand**, find the device, and use the three-dot menu → **Disable**. Disabling a device disables all of its entities at once and survives integration reloads. To act on many devices at once, use the **Devices** tab filter to narrow the list (e.g. filter by integration = Dockhand), then select multiple rows and use the bulk action menu.
