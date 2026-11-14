# Actions and automations

The integration's actions, starting and stopping containers and stacks, and example automations. [Back to the README](../README.md)

## Actions

Two actions, for administrators only (they delete data or replace a container):

| Action | Does | Fields |
|---|---|---|
| `dockhand.prune` | Deletes unused Docker resources in one environment and returns what was removed (`space_reclaimed` in bytes, and `images_deleted` etc. per resource) | `device_id`: the environment's device. `resources`: any of `containers` (stopped ones), `images`, `volumes`, `networks`. `all_images`: also delete tagged images no container uses, not only dangling ones (default off) |
| `dockhand.recreate_container` | Recreates a container from its current configuration, as saving it in Dockhand's editor does — a container that was running is started again | `device_id`: the container's device. `pull`: pull its image again first, picking up a newer image under the same tag (default on). Not for Dockhand's own container or Hawser agents |

```yaml
automation:
  - alias: "Weekly Docker clean-up"
    triggers:
      - trigger: time
        at: "04:00:00"
    conditions:
      - condition: time
        weekday: sun
    actions:
      - action: dockhand.prune
        data:
          device_id: 0123456789abcdef0123456789abcdef  # the environment's device
          resources: [containers, images, networks]
        response_variable: pruned
      - action: persistent_notification.create
        data:
          message: "Freed {{ (pruned.space_reclaimed / 1048576) | round(1) }} MiB"
```

## Container and Stack controls

| What you want | How to do it |
|---|---|
| Start a stopped container | Turn **Container** switch **on** |
| Stop a running container | Turn **Container** switch **off** |
| Start a stopped stack | Turn **Stack** switch **on** |
| Stop a running stack | Turn **Stack** switch **off** |
| Restart a container or stack | Press **Restart** button |

**Restart** works whatever state the container or stack is in, as in Dockhand: a stopped one is simply started.


## Example automations

The entity IDs below follow the [entity ID convention](entities.md#device-model) for an environment named `myenv` with a stand-alone container named `traefik`; use your own from **Settings → Entities**.

**Notify when a container stops**

```yaml
automation:
  - alias: "Alert when traefik stops"
    triggers:
      - trigger: state
        entity_id: sensor.myenv_containers_traefik_state
        to: exited
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "Container down"
          message: "traefik has stopped"
```

**Restart a container that stays unhealthy** (the Health sensor exists only for containers with a Docker healthcheck)

```yaml
automation:
  - alias: "Restart traefik when unhealthy"
    triggers:
      - trigger: state
        entity_id: sensor.myenv_containers_traefik_health
        to: unhealthy
        for:
          minutes: 5
    actions:
      - action: button.press
        target:
          entity_id: button.myenv_containers_traefik_restart
```

**Notify when a Docker host goes offline**

```yaml
automation:
  - alias: "Alert when myenv is offline"
    triggers:
      - trigger: state
        entity_id: binary_sensor.myenv_online
        to: "off"
        for:
          minutes: 2
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: "Docker host offline"
          message: "Dockhand can't reach myenv"
```
