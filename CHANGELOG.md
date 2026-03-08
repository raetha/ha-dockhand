# Changelog

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
