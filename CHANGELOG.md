# Changelog

## 1.0.1 — 2026-03-19

Patch release fixing entity ID suffix accumulation, stale entity cleanup, and icons.

### Bug fixes
- Fixed: stack devices pre-registered with bare name instead of environment-prefixed name (e.g. `traefik` instead of `Heimdall – traefik`), causing entity IDs for compose-managed containers to be generated without the environment prefix and colliding across environments
- Fixed: stale cleanup listeners were registered after platform setup, so cleanup fired after `async_add_entities` rather than before — allowing old and new container/image devices to briefly coexist and trigger `_2` suffixes on entity IDs
- Fixed: stale image, network, and volume entities were not cleaned up until the next slow coordinator poll (up to 600 s after reload); cleanup now runs immediately on integration setup so pruned resources are removed before new entities are registered
- Fixed: `icons.json` entries were never applied because no entity had `_attr_translation_key` set and `strings.json` lacked the required `entity` section; all 22 statically-named entities now declare their translation key
- Fixed: image and network sensors were missing `_attr_icon`; all three dynamic-name sensor types (image, network, volume) now have correct fallback icons

### Documentation
- README: added session timeout guidance — Dockhand defaults to 24 h; instructions to extend via Settings → Authentication → General → Session timeout
- README: added troubleshooting entry for `_2`/`_3` entity ID suffixes and how to resolve with Recreate entity IDs after a prune cycle

## 1.0.0 — 2026-03-08

Initial stable release of the Dockhand integration for Home Assistant.

### Architecture
- Dual-coordinator polling: fast (default 60 s) for containers, stacks, and environment stats; slow (default 600 s) for images, volumes, networks, and schedules
- Grouped device hierarchy per environment: `<Env> – Containers`, `<Env> – Stacks`, `<Env> – Networks`, `<Env> – Images`, `<Env> – Volumes`
- All resource devices prefixed with environment name (e.g. `Heimdall – traefik`) to disambiguate across environments
- `model` field on every device for type display in the HA device list
- Deep links from every device to its corresponding page in the Dockhand UI
- Stale device cleanup on coordinator refresh

### Authentication
- Local Dockhand user authentication with session-cookie persistence
- Full MFA (TOTP) support during setup, reconfigure, and re-authentication
- Options and Reconfigure flows to change poll intervals, feature flags, URL, or credentials without reinstalling

### Entities
- **Environment:** Online (binary_sensor), CPU usage, Memory usage, Containers running
- **Container:** State sensor, Health sensor (omitted if no healthcheck), Running switch (start/stop), Restart button
- **Stack:** Status sensor, Running switch (start/stop), Restart button
- **Network:** Connected container count with driver, scope, subnet, and container list attributes (optional)
- **Volume:** Connected container count with driver, mountpoint, and size attributes (optional)
- **Image:** Repository name with tag as state, size and container usage as attributes (optional)
- **Schedule:** Next run timestamp, Last status with error detail (optional, read-only)

### Quality
- 211 unit tests covering API client, config flow, coordinators, entities, and setup/teardown
- Passes hassfest and HACS validation
- Ruff lint clean
