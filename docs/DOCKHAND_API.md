# Dockhand REST API — generated reference

> Auto-generated from Dockhand's `src/routes/api/**/+server.ts` source
> (SvelteKit route handlers) via `scripts/generate_dockhand_api_docs.py`.
> Dockhand does not publish an OpenAPI spec (Finsys/dockhand#814 is open,
> unimplemented, as of this generation). This is a best-effort mechanical
> extraction — method + any leading doc comment + locally-declared
> TypeScript interfaces. It is NOT authoritative for request/response
> shapes; verify against source before depending on exact fields.

Total routes discovered: 208

## activity

### `DELETE, GET` `/activity`
- Source: `src/routes/api/activity/+server.ts`

### `GET` `/activity/containers`
- Source: `src/routes/api/activity/containers/+server.ts`

### `GET` `/activity/events`
- Source: `src/routes/api/activity/events/+server.ts`

### `GET` `/activity/stats`
- Source: `src/routes/api/activity/stats/+server.ts`

## audit

### `GET` `/audit`
- Source: `src/routes/api/audit/+server.ts`

### `GET` `/audit/events`
- Source: `src/routes/api/audit/events/+server.ts`

### `GET` `/audit/export`
- Source: `src/routes/api/audit/export/+server.ts`

### `GET` `/audit/users`
- Source: `src/routes/api/audit/users/+server.ts`

## auth

### `GET, POST` `/auth/ldap`
- Source: `src/routes/api/auth/ldap/+server.ts`

### `DELETE, GET, PUT` `/auth/ldap/[id]`
- Source: `src/routes/api/auth/ldap/[id]/+server.ts`

### `POST` `/auth/ldap/[id]/test`
- Source: `src/routes/api/auth/ldap/[id]/test/+server.ts`

### `POST` `/auth/login`
- Source: `src/routes/api/auth/login/+server.ts`

### `POST` `/auth/logout`
- Source: `src/routes/api/auth/logout/+server.ts`

### `GET, POST` `/auth/oidc`
- Source: `src/routes/api/auth/oidc/+server.ts`

### `DELETE, GET, PUT` `/auth/oidc/[id]`
- Source: `src/routes/api/auth/oidc/[id]/+server.ts`

### `GET, POST` `/auth/oidc/[id]/initiate`
- Source: `src/routes/api/auth/oidc/[id]/initiate/+server.ts`

### `POST` `/auth/oidc/[id]/test`
- Source: `src/routes/api/auth/oidc/[id]/test/+server.ts`

### `GET` `/auth/oidc/callback`
- Source: `src/routes/api/auth/oidc/callback/+server.ts`

### `GET` `/auth/providers`
- Source: `src/routes/api/auth/providers/+server.ts`

### `GET` `/auth/session`
- Source: `src/routes/api/auth/session/+server.ts`

### `GET, PUT` `/auth/settings`
- Source: `src/routes/api/auth/settings/+server.ts`

### `GET, POST` `/auth/tokens`
- Source: `src/routes/api/auth/tokens/+server.ts`

### `DELETE` `/auth/tokens/[id]`
DELETE /api/auth/tokens/[id] - Revoke an API token
- Source: `src/routes/api/auth/tokens/[id]/+server.ts`

## auto-update

### `GET` `/auto-update`
Batch endpoint to get all auto-update settings for an environment. Returns a map of containerName -> settings for efficient lookup.
- Source: `src/routes/api/auto-update/+server.ts`

### `DELETE, GET, POST` `/auto-update/[containerName]`
- Source: `src/routes/api/auto-update/[containerName]/+server.ts`

## batch

### `POST` `/batch`
- Local interfaces: `BatchStartEvent`, `BatchProgressEvent`, `BatchCompleteEvent`, `BatchErrorEvent`, `BatchRequest`
- Source: `src/routes/api/batch/+server.ts`

## changelog

### `GET` `/changelog`
- Source: `src/routes/api/changelog/+server.ts`

## config-sets

### `GET, POST` `/config-sets`
- Source: `src/routes/api/config-sets/+server.ts`

### `DELETE, GET, PUT` `/config-sets/[id]`
- Source: `src/routes/api/config-sets/[id]/+server.ts`

## containers

### `GET, POST` `/containers`
- Source: `src/routes/api/containers/+server.ts`

### `DELETE, GET` `/containers/[id]`
- Source: `src/routes/api/containers/[id]/+server.ts`

### `POST` `/containers/[id]/exec`
Container Exec API POST: Creates an exec instance for terminal attachment Returns exec ID that can be used for WebSocket connection
- Source: `src/routes/api/containers/[id]/exec/+server.ts`

### `GET` `/containers/[id]/files`
- Source: `src/routes/api/containers/[id]/files/+server.ts`

### `POST` `/containers/[id]/files/chmod`
- Source: `src/routes/api/containers/[id]/files/chmod/+server.ts`

### `GET, PUT` `/containers/[id]/files/content`
- Source: `src/routes/api/containers/[id]/files/content/+server.ts`

### `POST` `/containers/[id]/files/create`
- Source: `src/routes/api/containers/[id]/files/create/+server.ts`

### `DELETE` `/containers/[id]/files/delete`
- Source: `src/routes/api/containers/[id]/files/delete/+server.ts`

### `GET` `/containers/[id]/files/download`
- Source: `src/routes/api/containers/[id]/files/download/+server.ts`

### `POST` `/containers/[id]/files/rename`
- Source: `src/routes/api/containers/[id]/files/rename/+server.ts`

### `POST` `/containers/[id]/files/upload`
Create a simple tar archive from a single file TAR format: 512-byte header followed by file content padded to 512 bytes
- Source: `src/routes/api/containers/[id]/files/upload/+server.ts`

### `GET` `/containers/[id]/inspect`
- Source: `src/routes/api/containers/[id]/inspect/+server.ts`

### `GET` `/containers/[id]/logs`
- Source: `src/routes/api/containers/[id]/logs/+server.ts`

### `GET` `/containers/[id]/logs/stream`
- Local interfaces: `DockerClientConfig`
- Source: `src/routes/api/containers/[id]/logs/stream/+server.ts`

### `POST` `/containers/[id]/pause`
- Source: `src/routes/api/containers/[id]/pause/+server.ts`

### `POST` `/containers/[id]/rename`
- Source: `src/routes/api/containers/[id]/rename/+server.ts`

### `POST` `/containers/[id]/restart`
- Source: `src/routes/api/containers/[id]/restart/+server.ts`

### `GET` `/containers/[id]/shells`
- Source: `src/routes/api/containers/[id]/shells/+server.ts`

### `POST` `/containers/[id]/start`
- Source: `src/routes/api/containers/[id]/start/+server.ts`

### `GET` `/containers/[id]/stats`
- Source: `src/routes/api/containers/[id]/stats/+server.ts`

### `POST` `/containers/[id]/stop`
- Source: `src/routes/api/containers/[id]/stop/+server.ts`

### `GET` `/containers/[id]/top`
- Source: `src/routes/api/containers/[id]/top/+server.ts`

### `POST` `/containers/[id]/unpause`
- Source: `src/routes/api/containers/[id]/unpause/+server.ts`

### `POST` `/containers/[id]/update`
- Source: `src/routes/api/containers/[id]/update/+server.ts`

### `POST` `/containers/[id]/update-runtime`
POST /api/containers/[id]/update-runtime In-place update of a running container's restart policy, CPU/memory limits, blkio weights, and pids limit — the only properties Docker can change without recreating the container. The body must contain ONLY fields from IN_PLACE_UPDATE_FIELDS (see docker.ts); any unknown fields are silently dropped so a confused or malicious caller can't sneak a recreate-only field (image, env, ports, etc.) through this path. Returns Docker's response — typically `{ Warnings: string[] | null }`.
- Source: `src/routes/api/containers/[id]/update-runtime/+server.ts`

### `POST` `/containers/batch-update`
- Local interfaces: `BatchUpdateResult`
- Source: `src/routes/api/containers/batch-update/+server.ts`

### `POST` `/containers/batch-update-stream`
- Local interfaces: `ScanResult`, `UpdateProgress`
- Source: `src/routes/api/containers/batch-update-stream/+server.ts`

### `GET, POST` `/containers/check-updates`
- Local interfaces: `UpdateCheckResult`
- Source: `src/routes/api/containers/check-updates/+server.ts`

### `DELETE, GET` `/containers/pending-updates`
Get pending container updates for an environment.
- Source: `src/routes/api/containers/pending-updates/+server.ts`

### `GET` `/containers/sizes`
- Source: `src/routes/api/containers/sizes/+server.ts`

### `GET` `/containers/stats`
- Source: `src/routes/api/containers/stats/+server.ts`

### `GET` `/containers/stats/stream`
- Source: `src/routes/api/containers/stats/stream/+server.ts`

## dashboard

### `GET, POST` `/dashboard/preferences`
- Local interfaces: `StoredDashboardPrefs`
- Source: `src/routes/api/dashboard/preferences/+server.ts`

### `GET` `/dashboard/stats`
- Local interfaces: `LoadingStates`, `EnvironmentStats`
- Source: `src/routes/api/dashboard/stats/+server.ts`

### `GET` `/dashboard/stats/stream`
- Local interfaces: `DiskUsageCache`
- Source: `src/routes/api/dashboard/stats/stream/+server.ts`

## debug

### `GET` `/debug/memory`
Memory Debug Endpoint Returns Node.js memory stats for monitoring. Only available when MEMORY_MONITOR=true environment variable is set. GET /api/debug/memory        - Memory stats (with optional ?gc=true to force GC first) GET /api/debug/memory?gc=true - Force garbage collection before reporting
- Source: `src/routes/api/debug/memory/+server.ts`

## dependencies

### `GET` `/dependencies`
- Source: `src/routes/api/dependencies/+server.ts`

## environments

### `GET, POST` `/environments`
- Source: `src/routes/api/environments/+server.ts`

### `DELETE, GET, PUT` `/environments/[id]`
- Source: `src/routes/api/environments/[id]/+server.ts`

### `GET, POST` `/environments/[id]/disk-warning`
- Source: `src/routes/api/environments/[id]/disk-warning/+server.ts`

### `DELETE, GET, POST` `/environments/[id]/icon`
- Source: `src/routes/api/environments/[id]/icon/+server.ts`

### `GET, POST, PUT` `/environments/[id]/image-prune`
Get image prune settings for an environment.
- Source: `src/routes/api/environments/[id]/image-prune/+server.ts`

### `GET, POST` `/environments/[id]/notifications`
- Source: `src/routes/api/environments/[id]/notifications/+server.ts`

### `DELETE, GET, PUT` `/environments/[id]/notifications/[notificationId]`
- Source: `src/routes/api/environments/[id]/notifications/[notificationId]/+server.ts`

### `POST` `/environments/[id]/test`
- Source: `src/routes/api/environments/[id]/test/+server.ts`

### `GET, POST` `/environments/[id]/timezone`
Map of modern IANA timezone names to their canonical equivalents recognized by ICU
- Source: `src/routes/api/environments/[id]/timezone/+server.ts`

### `GET, POST` `/environments/[id]/update-check`
Get update check settings for an environment.
- Source: `src/routes/api/environments/[id]/update-check/+server.ts`

### `GET` `/environments/detect-socket`
Detect available Docker sockets on the system
- Local interfaces: `DetectedSocket`
- Source: `src/routes/api/environments/detect-socket/+server.ts`

### `POST` `/environments/test`
- Local interfaces: `TestConnectionRequest`
- Source: `src/routes/api/environments/test/+server.ts`

## events

### `GET` `/events`
- Source: `src/routes/api/events/+server.ts`

## git

### `GET, POST` `/git/credentials`
- Source: `src/routes/api/git/credentials/+server.ts`

### `DELETE, GET, PUT` `/git/credentials/[id]`
- Source: `src/routes/api/git/credentials/[id]/+server.ts`

### `POST` `/git/preview-env`
POST /api/git/preview-env Clone a git repository to a temp directory and read env files for preview. Used when creating a new git stack to populate the env editor. Body: {   repositoryId?: number,           // Existing repository   url?: string,                    // OR new repo URL   branch?: string,                 // Branch (default: main)   credentialId?: number,           // Credential for auth   composePath: string,             // Path to compose file   envFilePath?: string             // Optional additional env file } Returns: {   vars: Record<string, string>,    // Merged env variables   sources: {                       // Which file each var came from     [key: string]: '.env' | 'envFile'   },   error?: string }
- Source: `src/routes/api/git/preview-env/+server.ts`

### `GET, POST` `/git/repositories`
- Source: `src/routes/api/git/repositories/+server.ts`

### `DELETE, GET, PUT` `/git/repositories/[id]`
- Source: `src/routes/api/git/repositories/[id]/+server.ts`

### `POST` `/git/repositories/[id]/deploy`
- Source: `src/routes/api/git/repositories/[id]/deploy/+server.ts`

### `GET, POST` `/git/repositories/[id]/sync`
- Source: `src/routes/api/git/repositories/[id]/sync/+server.ts`

### `POST` `/git/repositories/[id]/test`
- Source: `src/routes/api/git/repositories/[id]/test/+server.ts`

### `POST` `/git/repositories/test`
POST /api/git/repositories/test Test a git repository configuration before saving. Uses stored credentials via credentialId. Body: {   url: string;           // Repository URL to test   branch: string;        // Branch name to verify   credentialId?: number; // Optional credential ID from database }
- Source: `src/routes/api/git/repositories/test/+server.ts`

### `GET, POST` `/git/stacks`
- Source: `src/routes/api/git/stacks/+server.ts`

### `DELETE, GET, PUT` `/git/stacks/[id]`
- Source: `src/routes/api/git/stacks/[id]/+server.ts`

### `POST` `/git/stacks/[id]/deploy`
- Source: `src/routes/api/git/stacks/[id]/deploy/+server.ts`

### `POST` `/git/stacks/[id]/deploy-stream`
- Source: `src/routes/api/git/stacks/[id]/deploy-stream/+server.ts`

### `GET, POST` `/git/stacks/[id]/env-files`
GET /api/git/stacks/[id]/env-files List all .env files in the git stack's repository. Returns: { files: string[] }
- Source: `src/routes/api/git/stacks/[id]/env-files/+server.ts`

### `POST` `/git/stacks/[id]/sync`
- Source: `src/routes/api/git/stacks/[id]/sync/+server.ts`

### `POST` `/git/stacks/[id]/test`
- Source: `src/routes/api/git/stacks/[id]/test/+server.ts`

### `GET, POST` `/git/stacks/[id]/webhook`
- Source: `src/routes/api/git/stacks/[id]/webhook/+server.ts`

### `GET, POST` `/git/webhook/[id]`
- Source: `src/routes/api/git/webhook/[id]/+server.ts`

## hawser

### `GET, POST` `/hawser/connect`
Hawser Edge WebSocket Connect Endpoint This endpoint handles WebSocket connections from Hawser agents running in Edge mode. In development: WebSocket is handled by ws.WebSocketServer in vite.config.ts on port 5174 In production: WebSocket is handled by the server wrapper in server.ts The HTTP GET endpoint returns connection info for clients.
- Source: `src/routes/api/hawser/connect/+server.ts`

### `DELETE, GET, POST` `/hawser/tokens`
Hawser Token Management API Handles CRUD operations for Hawser agent tokens.
- Source: `src/routes/api/hawser/tokens/+server.ts`

## health

### `GET` `/health`
- Source: `src/routes/api/health/+server.ts`

### `GET` `/health/database`
Database Health Check Endpoint Public endpoint suitable for external monitoring. The public payload reports enough detail to detect schema drift and table loss without exposing connection details (host, port, db name, user) or the running migration tag. Authenticated callers with settings:view get the full payload — connection string (password masked) and schema version included — which is useful for operators debugging from the admin UI. GET /api/health/database
- Source: `src/routes/api/health/database/+server.ts`

## host

### `GET` `/host`
- Local interfaces: `HostInfo`
- Source: `src/routes/api/host/+server.ts`

## images

### `GET` `/images`
- Source: `src/routes/api/images/+server.ts`

### `DELETE` `/images/[id]`
- Source: `src/routes/api/images/[id]/+server.ts`

### `GET` `/images/[id]/export`
- Source: `src/routes/api/images/[id]/export/+server.ts`

### `GET` `/images/[id]/history`
- Source: `src/routes/api/images/[id]/history/+server.ts`

### `POST` `/images/[id]/tag`
- Source: `src/routes/api/images/[id]/tag/+server.ts`

### `POST` `/images/pull`
- Source: `src/routes/api/images/pull/+server.ts`

### `POST` `/images/push`
- Source: `src/routes/api/images/push/+server.ts`

### `GET, POST` `/images/scan`
- Source: `src/routes/api/images/scan/+server.ts`

### `GET` `/images/scan/export`
Per-image vulnerability export (#415): reformats the cached scan for one image as json | csv | sarif for CI / DefectDojo / Dependency-Track integration. Read-only over persisted scans; no new scanning. Auth via cookie or Bearer token (CI), with RBAC + enterprise environment scoping.
- Source: `src/routes/api/images/scan/export/+server.ts`

## jobs

### `DELETE, GET` `/jobs/[id]`
GET /api/jobs/[id] Poll a job's status and accumulated lines. Returns all lines every time — client tracks its own cursor locally. No auth required: job IDs are UUIDs (unguessable), no sensitive data beyond what the initiating user triggered.
- Source: `src/routes/api/jobs/[id]/+server.ts`

## labels

### `GET, POST` `/labels`
- Source: `src/routes/api/labels/+server.ts`

## legal

### `GET` `/legal/license`
- Source: `src/routes/api/legal/license/+server.ts`

### `GET` `/legal/privacy`
- Source: `src/routes/api/legal/privacy/+server.ts`

## license

### `DELETE, GET, POST` `/license`
- Source: `src/routes/api/license/+server.ts`

## logs

### `GET` `/logs/merged`
- Local interfaces: `DockerClientConfig`, `ContainerLogSource`, `EdgeContainerLogSource`
- Source: `src/routes/api/logs/merged/+server.ts`

## networks

### `GET, POST` `/networks`
- Source: `src/routes/api/networks/+server.ts`

### `DELETE, GET` `/networks/[id]`
- Source: `src/routes/api/networks/[id]/+server.ts`

### `POST` `/networks/[id]/connect`
- Source: `src/routes/api/networks/[id]/connect/+server.ts`

### `POST` `/networks/[id]/disconnect`
- Source: `src/routes/api/networks/[id]/disconnect/+server.ts`

### `GET` `/networks/[id]/inspect`
- Source: `src/routes/api/networks/[id]/inspect/+server.ts`

## notifications

### `GET, POST` `/notifications`
- Source: `src/routes/api/notifications/+server.ts`

### `DELETE, GET, PUT` `/notifications/[id]`
- Source: `src/routes/api/notifications/[id]/+server.ts`

### `POST` `/notifications/[id]/test`
- Source: `src/routes/api/notifications/[id]/test/+server.ts`

### `POST` `/notifications/test`
- Source: `src/routes/api/notifications/test/+server.ts`

### `GET, POST` `/notifications/trigger-test`
Test endpoint to trigger notifications for any event type. This is intended for development/testing purposes only. POST /api/notifications/trigger-test Body: {   eventType: string,   environmentId?: number,   payload: { title: string, message: string, type?: string } }
- Source: `src/routes/api/notifications/trigger-test/+server.ts`

## preferences

### `GET, POST` `/preferences/favorite-groups`
- Local interfaces: `FavoriteGroup`
- Source: `src/routes/api/preferences/favorite-groups/+server.ts`

### `GET, POST` `/preferences/favorites`
- Source: `src/routes/api/preferences/favorites/+server.ts`

### `DELETE, GET, POST` `/preferences/grid`
- Source: `src/routes/api/preferences/grid/+server.ts`

### `DELETE, GET, POST` `/preferences/sidebar`
- Source: `src/routes/api/preferences/sidebar/+server.ts`

## profile

### `GET, PUT` `/profile`
- Source: `src/routes/api/profile/+server.ts`

### `DELETE, POST` `/profile/avatar`
- Source: `src/routes/api/profile/avatar/+server.ts`

### `GET, PUT` `/profile/preferences`
- Source: `src/routes/api/profile/preferences/+server.ts`

## prune

### `POST` `/prune/all`
- Source: `src/routes/api/prune/all/+server.ts`

### `POST` `/prune/containers`
- Source: `src/routes/api/prune/containers/+server.ts`

### `POST` `/prune/images`
- Source: `src/routes/api/prune/images/+server.ts`

### `POST` `/prune/networks`
- Source: `src/routes/api/prune/networks/+server.ts`

### `POST` `/prune/volumes`
- Source: `src/routes/api/prune/volumes/+server.ts`

## registries

### `GET, POST` `/registries`
- Source: `src/routes/api/registries/+server.ts`

### `DELETE, GET, PUT` `/registries/[id]`
- Source: `src/routes/api/registries/[id]/+server.ts`

### `POST` `/registries/[id]/default`
- Source: `src/routes/api/registries/[id]/default/+server.ts`

### `POST` `/registries/test`
Test registry connectivity and credentials. Accepts either inline credentials (from the modal form) or a registry ID (to test an already-saved registry using stored credentials).
- Source: `src/routes/api/registries/test/+server.ts`

## registry

### `GET` `/registry/catalog`
- Source: `src/routes/api/registry/catalog/+server.ts`

### `DELETE` `/registry/image`
- Source: `src/routes/api/registry/image/+server.ts`

### `GET` `/registry/search`
- Local interfaces: `SearchResult`
- Source: `src/routes/api/registry/search/+server.ts`

### `GET` `/registry/tags`
- Local interfaces: `TagInfo`, `PaginatedTags`
- Source: `src/routes/api/registry/tags/+server.ts`

## roles

### `GET, POST` `/roles`
- Source: `src/routes/api/roles/+server.ts`

### `DELETE, GET, PUT` `/roles/[id]`
- Source: `src/routes/api/roles/[id]/+server.ts`

## schedules

### `GET` `/schedules`
Schedules API - List all active schedules GET /api/schedules - Returns all enabled schedules (container auto-updates, git stack syncs, and system jobs)
- Local interfaces: `ScheduleInfo`
- Source: `src/routes/api/schedules/+server.ts`

### `DELETE` `/schedules/[type]/[id]`
Delete schedule DELETE /api/schedules/:type/:id
- Source: `src/routes/api/schedules/[type]/[id]/+server.ts`

### `POST` `/schedules/[type]/[id]/run`
Manual Schedule Trigger API - Manually run a schedule POST /api/schedules/[type]/[id]/run - Trigger a manual execution Path params:   - type: 'container_update' | 'git_stack_sync' | 'system_cleanup' | 'env_update_check' | 'image_prune'   - id: schedule ID
- Source: `src/routes/api/schedules/[type]/[id]/run/+server.ts`

### `POST` `/schedules/[type]/[id]/toggle`
Toggle schedule enabled/disabled POST /api/schedules/:type/:id/toggle
- Source: `src/routes/api/schedules/[type]/[id]/toggle/+server.ts`

### `GET` `/schedules/executions`
Schedule Executions API - List execution history GET /api/schedules/executions - Returns paginated execution history Query params:   - scheduleType: 'container_update' | 'git_stack_sync'   - scheduleId: number   - environmentId: number   - status: 'queued' | 'running' | 'success' | 'failed' | 'skipped'   - triggeredBy: 'cron' | 'webhook' | 'manual'   - fromDate: ISO date string   - toDate: ISO date string   - limit: number (default 50)   - offset: number (default 0)
- Source: `src/routes/api/schedules/executions/+server.ts`

### `DELETE, GET` `/schedules/executions/[id]`
Schedule Execution Detail API GET /api/schedules/executions/[id] - Returns execution details including logs DELETE /api/schedules/executions/[id] - Delete a schedule execution
- Source: `src/routes/api/schedules/executions/[id]/+server.ts`

### `GET, PUT` `/schedules/settings`
Schedule Settings API - Get/set schedule display preferences GET /api/schedules/settings - Get current display settings PUT /api/schedules/settings - Update display settings Note: Data retention settings are now managed in /api/settings/general
- Source: `src/routes/api/schedules/settings/+server.ts`

### `GET` `/schedules/stream`
Schedules Stream API - Real-time schedule updates via SSE GET /api/schedules/stream - Server-Sent Events stream for schedule updates
- Source: `src/routes/api/schedules/stream/+server.ts`

### `POST` `/schedules/system/[id]/toggle`
- Source: `src/routes/api/schedules/system/[id]/toggle/+server.ts`

## self-update

### `POST` `/self-update`
- Source: `src/routes/api/self-update/+server.ts`

### `GET` `/self-update/check`
Fetch from the local Docker directly (not through environment routing)
- Source: `src/routes/api/self-update/check/+server.ts`

### `GET` `/self-update/progress`
Fetch from the local Docker directly. Supports TCP and Unix socket.
- Source: `src/routes/api/self-update/progress/+server.ts`

## settings

### `GET, POST` `/settings/general`
- Local interfaces: `GeneralSettings`
- Source: `src/routes/api/settings/general/+server.ts`

### `DELETE, GET, POST` `/settings/scanner`
- Local interfaces: `ScannerSettings`
- Source: `src/routes/api/settings/scanner/+server.ts`

### `DELETE` `/settings/scanner/cache`
- Source: `src/routes/api/settings/scanner/cache/+server.ts`

### `GET` `/settings/theme`
Public endpoint for theme settings - no authentication required. Used by the login page to apply the app-level theme before user is authenticated.
- Source: `src/routes/api/settings/theme/+server.ts`

## stacks

### `GET, POST` `/stacks`
- Source: `src/routes/api/stacks/+server.ts`

### `DELETE` `/stacks/[name]`
- Source: `src/routes/api/stacks/[name]/+server.ts`

### `POST` `/stacks/[name]/check-path-change`
POST /api/stacks/[name]/check-path-change Check if the proposed compose path differs from current and if old directory has files. Returns information about what would need to be moved if location changes.
- Source: `src/routes/api/stacks/[name]/check-path-change/+server.ts`

### `GET, PUT` `/stacks/[name]/compose`
- Source: `src/routes/api/stacks/[name]/compose/+server.ts`

### `POST` `/stacks/[name]/deploy`
- Source: `src/routes/api/stacks/[name]/deploy/+server.ts`

### `POST` `/stacks/[name]/down`
- Source: `src/routes/api/stacks/[name]/down/+server.ts`

### `GET, PUT` `/stacks/[name]/env`
Parse a .env file content into key-value pairs
- Source: `src/routes/api/stacks/[name]/env/+server.ts`

### `GET, PUT` `/stacks/[name]/env/raw`
GET /api/stacks/[name]/env/raw?env=X Get the raw .env file content as-is (with comments, formatting, etc.)
- Source: `src/routes/api/stacks/[name]/env/raw/+server.ts`

### `POST` `/stacks/[name]/env/validate`
Docker and Compose built-in env vars consumed implicitly at runtime (not via ${} interpolation)
- Local interfaces: `ValidationResult`
- Source: `src/routes/api/stacks/[name]/env/validate/+server.ts`

### `POST` `/stacks/[name]/relocate`
POST /api/stacks/[name]/relocate Move all stack files from old directory to new location. Updates the database with new paths and returns refreshed content.
- Source: `src/routes/api/stacks/[name]/relocate/+server.ts`

### `POST` `/stacks/[name]/restart`
- Source: `src/routes/api/stacks/[name]/restart/+server.ts`

### `POST` `/stacks/[name]/start`
- Source: `src/routes/api/stacks/[name]/start/+server.ts`

### `POST` `/stacks/[name]/stop`
- Source: `src/routes/api/stacks/[name]/stop/+server.ts`

### `POST` `/stacks/adopt`
- Source: `src/routes/api/stacks/adopt/+server.ts`

### `GET` `/stacks/base-path`
GET /api/stacks/base-path Returns the default Dockhand stacks directory path. This is where stacks are stored by default ($DATA_DIR/stacks/).
- Source: `src/routes/api/stacks/base-path/+server.ts`

### `GET` `/stacks/default-path`
Get the default path for a new stack Used by the UI to show where files will be created Query params: - name: Stack name (required) - env: Environment ID (optional) - location: Custom base location path (optional) If location is provided, path will be: {location}/{envName}/{stackName}/ Otherwise uses Dockhand's default: $DATA_DIR/stacks/{envName}/{stackName}/
- Source: `src/routes/api/stacks/default-path/+server.ts`

### `GET` `/stacks/path-hints`
GET /api/stacks/path-hints?name=stackName&env=envId Returns path hints extracted from Docker container labels for a stack.
- Source: `src/routes/api/stacks/path-hints/+server.ts`

### `POST` `/stacks/scan`
- Source: `src/routes/api/stacks/scan/+server.ts`

### `GET` `/stacks/sources`
- Source: `src/routes/api/stacks/sources/+server.ts`

### `POST` `/stacks/validate-path`
- Source: `src/routes/api/stacks/validate-path/+server.ts`

## system

### `GET` `/system`
- Source: `src/routes/api/system/+server.ts`

### `GET` `/system/disk`
- Source: `src/routes/api/system/disk/+server.ts`

### `GET, POST` `/system/files`
- Local interfaces: `FileEntry`
- Source: `src/routes/api/system/files/+server.ts`

### `GET` `/system/files/content`
GET /api/system/files/content Read file content from Dockhand's local filesystem Query params: - path: File path to read
- Source: `src/routes/api/system/files/content/+server.ts`

## templates

### `GET` `/templates`
- Local interfaces: `TemplateItem`
- Source: `src/routes/api/templates/+server.ts`

### `POST` `/templates/compose`
- Source: `src/routes/api/templates/compose/+server.ts`

### `DELETE, GET, POST, PUT` `/templates/sources`
- Source: `src/routes/api/templates/sources/+server.ts`

## users

### `GET, POST` `/users`
- Source: `src/routes/api/users/+server.ts`

### `DELETE, GET, PUT` `/users/[id]`
- Source: `src/routes/api/users/[id]/+server.ts`

### `DELETE, POST` `/users/[id]/mfa`
- Source: `src/routes/api/users/[id]/mfa/+server.ts`

### `DELETE, GET, POST` `/users/[id]/roles`
- Source: `src/routes/api/users/[id]/roles/+server.ts`

## volumes

### `GET, POST` `/volumes`
- Source: `src/routes/api/volumes/+server.ts`

### `DELETE, GET` `/volumes/[name]`
- Source: `src/routes/api/volumes/[name]/+server.ts`

### `GET` `/volumes/[name]/browse`
- Source: `src/routes/api/volumes/[name]/browse/+server.ts`

### `GET` `/volumes/[name]/browse/content`
- Source: `src/routes/api/volumes/[name]/browse/content/+server.ts`

### `POST` `/volumes/[name]/browse/release`
Release the cached volume helper container when done browsing. This is called when the volume browser modal is closed.
- Source: `src/routes/api/volumes/[name]/browse/release/+server.ts`

### `POST` `/volumes/[name]/clone`
- Source: `src/routes/api/volumes/[name]/clone/+server.ts`

### `GET` `/volumes/[name]/export`
- Source: `src/routes/api/volumes/[name]/export/+server.ts`

### `GET` `/volumes/[name]/inspect`
- Source: `src/routes/api/volumes/[name]/inspect/+server.ts`

## vulnerabilities

### `GET` `/vulnerabilities`
A page of aggregated vulnerability findings for an environment, filtered and sorted server-side. Query: limit, offset, q, severity, image, container, stack, sort, dir. Returns { findings, total } where `total` is the filtered count (for the "X-Y of N" counter and infinite scroll).
- Source: `src/routes/api/vulnerabilities/+server.ts`

### `GET` `/vulnerabilities/count`
Vulnerability dashboard metadata for an environment: the total finding count, the severity summary, and the distinct filter-dropdown values (image / container / stack) across the full set. Lets the header badge and the filter dropdowns stay complete without the page loading the full findings array.
- Source: `src/routes/api/vulnerabilities/count/+server.ts`

### `GET` `/vulnerabilities/export`
- Source: `src/routes/api/vulnerabilities/export/+server.ts`

### `POST` `/vulnerabilities/scan-all`
Scan every (tagged) image in the environment for vulnerabilities. Reuses the per-image scan flow, sequentially, reporting N/total progress. A single image failing does not abort the batch.
- Source: `src/routes/api/vulnerabilities/scan-all/+server.ts`
