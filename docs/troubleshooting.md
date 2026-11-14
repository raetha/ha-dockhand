# Troubleshooting and known limitations

[Back to the README](../README.md)

## Troubleshooting

**Cannot connect** Check the API URL is reachable from the HA host. If authentication is enabled, confirm your API token starts with `dh_` and was copied in full.

**Entity IDs have a `_2` or `_3` suffix after a container or image update** Image sensors specifically now avoid this in the common case: when a container update causes two images to briefly claim the same tag (the newly-pulled one, and the old one not yet marked untagged), the integration waits for that to settle — usually resolved within a poll cycle or two — rather than creating a colliding entity. If you still see a suffix (a device or entity type not covered by that handling, or an unusually long-lived ambiguity), it means HA created a new entity while an old one with the same natural ID still technically existed at that moment. Once the old object is gone and the integration has reloaded or polled, go to **Settings → Devices & Services → ⋮ → Recreate entity IDs** on the Dockhand integration card to reclaim the clean ID — HA will rename any suffixed entity whose "natural" ID is now free. Any automations or dashboard cards referencing the suffixed ID will need to be updated after the rename.

**No entities appear after setup** Check HA logs for errors containing `dockhand`. Ensure the user account has permission to view all environments.

**A device for a container or stack you've removed is still there** Devices are removed automatically once Dockhand confirms the container, stack or environment is gone, but kept while that can't be confirmed — the environment is offline, or its last fetch failed — so a brief outage never deletes anything. If one is left behind (an environment deleted while offline, say), open the device and use **Delete** in its three-dot menu. Deleting is refused for a device Dockhand still reports, since the next poll would only bring it back.

**No update shown for Dockhand or a Hawser agent** Check the image tag those containers run. With a pinned version tag, Dockhand itself never reports a newer one for them through its containers API; see the note on updates for Dockhand and Hawser under [Stack](entities.md#stack-always-on-60-s). Moving them to a floating tag such as `latest` is the reliable fix. The integration's diagnostics download lists what Dockhand last reported for each system container (`system_containers`) and what Dockhand's own release check found (`self_update`).

**A schedule has no Run now button or Enabled switch** Both follow what Dockhand's own Schedules page offers. Environment reports and stack deploys can't be run on demand. Container update and Git stack sync schedules are turned on and off with the container's **Auto update** and the stack's **Auto deploy** switches instead, and Dockhand's backup-repository jobs and its deploy-log housekeeping can't be paused.


## Known limitations

- **Live updates need Dockhand to watch an environment's Docker events.** Environments that collect neither activity nor metrics, or a token without `activity: view`, only change on the next poll (see [Data Updates](data-updates.md)). Totals such as an environment's running-container count also come from the poll.
- **Dockhand's Poll event collection mode delays and drops events.** Keep it on Stream (see [Data Updates](data-updates.md)).
- **Some schedules can't be paused or run from here.** Dockhand can't run scheduled reports or stack deploys on demand, and can't pause backup-repository maintenance without it disappearing from its schedule list, so those get no Run now or Enabled entity.
- **No build-cache pruning.** Dockhand's API has no build-cache prune, so `dockhand.prune` can't do it either.
- **Runtime controls only for stand-alone containers.** Memory, CPU and process limits and the restart policy can't be changed live for a Compose-managed container, since the stack's own compose file would put them back.
- **Pinned-version Dockhand and Hawser images get limited update notices.** Dockhand never reports a newer version tag for its own container or a Hawser agent. A pinned Dockhand is covered by Dockhand's own release check where it can see its own container; a pinned Hawser isn't covered at all. See the notes at the end of [Stack](entities.md#stack-always-on-60-s) — a floating tag avoids both.
- **No controls for system containers.** Dockhand's own container and Hawser agents (and stacks containing one) get no start/stop/restart switch, button or runtime controls, matching Dockhand's own UI. Dockhand's scheduled update check skips them too, so their updates are found only by **Check for image updates**.
- **Install can't move a container to a newer version tag.** When Dockhand reports a newer tag (say `2.0` while you run `1.9`), moving to it means changing the image tag in the container's or stack's configuration; Install only applies updates to the tag you already use.
- **Install can't update an image pinned to a digest.** A container running `image:tag@sha256:…` always gets exactly that image. When the tag moves on, its update entity says so (`pinned_digest_moved`), but the update is changing the pin in its compose file.
- **Git stack deploys follow the stack's own settings.** Whether a deploy pulls fresh images is the git stack's "repull images" setting in Dockhand; it can't be overridden per press.
- **Resource stats only for running containers.** Stopped containers' CPU, memory, network and disk sensors are unavailable, as Dockhand reports nothing for them.
- **Containers labelled `dockhand.hidden=true` never appear**, since Dockhand leaves them out of its API.
