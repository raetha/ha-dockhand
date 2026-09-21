# Dockhand REST API — generated reference

> Auto-generated from Dockhand's `src/routes/api/**/+server.ts` source
> (SvelteKit route handlers) via `scripts/generate_dockhand_api_docs.py`.
> Dockhand does not publish an OpenAPI spec (Finsys/dockhand#814 is open,
> unimplemented, as of this generation). This is a best-effort mechanical
> extraction — method + any leading doc comment + locally-declared
> TypeScript interfaces. It is NOT authoritative for request/response
> shapes; verify against source before depending on exact fields.

Total routes discovered: 257

## activity

### `DELETE, GET` `/activity`
@openapi summary: Query container activity events with filters and pagination query: environmentId:integer Filter to a single environment (from GET /api/environments) query: containerId:string Filter by container ID (from GET /api/containers) query: containerName:string Filter by container name query: actions:string Comma-separated event actions to filter by query: labels:string Comma-separated labels to filter by query: fromDate:string Start of the date range (ISO 8601) query: toDate:string End of the date range (ISO 8601) query: limit:integer Maximum number of events to return query: offset:integer Number of events to skip (pagination) resp-200: {events:array<{id:integer!, containerName:string, action:string, timestamp:string}>, total:integer!, limit:integer!, offset:integer!} resp-403: Permission denied (requires the activity:view permission) resp-500: Failed to fetch container events
- Source: `src/routes/api/activity/+server.ts`

### `GET` `/activity/containers`
@openapi summary: List distinct container names that appear in the activity log, for filter dropdowns query: environment_id:integer Filter to a single environment (from GET /api/environments) resp-200: array<string> resp-200-example: ["web-1","db-1","cache-1"] resp-403: Permission denied (requires the activity:view permission) resp-500: Failed to fetch container names
- Source: `src/routes/api/activity/containers/+server.ts`

### `GET` `/activity/events`
@openapi summary: Stream live container activity and environment-status events over Server-Sent Events resp-200: Server-Sent Events stream (text/event-stream) emitting connected, heartbeat, activity and env_status events resp-403: Permission denied (requires the activity:view permission)
- Source: `src/routes/api/activity/events/+server.ts`

### `GET` `/activity/stats`
@openapi summary: Get aggregate container activity statistics (totals and counts by action) query: environment_id:integer Filter to a single environment (from GET /api/environments) resp-200: {total:integer!, today:integer!, byAction:{}} resp-200-example: {"total":128,"today":7,"byAction":{"start":40,"stop":30}} resp-403: Permission denied (requires the activity:view permission) resp-500: Failed to fetch stats
- Source: `src/routes/api/activity/stats/+server.ts`

## audit

### `GET` `/audit`
@openapi summary: Query the audit log with filters and pagination (Enterprise only) query: usernames:string Comma-separated usernames to filter by query: entityTypes:string Comma-separated entity types to filter by query: actions:string Comma-separated actions to filter by query: username:string Legacy single-username filter query: entityType:string Legacy single entity-type filter query: action:string Legacy single-action filter query: environmentId:integer Filter to a single environment (from GET /api/environments) query: labels:string Comma-separated labels to filter by query: fromDate:string Start of the date range (ISO 8601) query: toDate:string End of the date range (ISO 8601) query: limit:integer Maximum number of entries to return query: offset:integer Number of entries to skip (pagination) resp-200: {logs:array<{id:integer!, username:string, action:string, entityType:string, entityName:string, createdAt:string}>, total:integer} resp-403: Enterprise required, or permission denied resp-500: Failed to fetch audit logs
- Source: `src/routes/api/audit/+server.ts`

### `GET` `/audit/events`
@openapi summary: Stream live audit-log events over Server-Sent Events (Enterprise only) resp-200: Server-Sent Events stream (text/event-stream) emitting connected, heartbeat and audit events resp-403: Enterprise required, or permission denied
- Source: `src/routes/api/audit/events/+server.ts`

### `GET` `/audit/export`
- Source: `src/routes/api/audit/export/+server.ts`

### `GET` `/audit/users`
@openapi summary: List the distinct usernames that appear in the audit log, for filter dropdowns (Enterprise only) resp-200: array<string> resp-200-example: ["admin","ci-bot","alice"] resp-403: Enterprise required, or permission denied resp-500: Failed to fetch audit log users
- Source: `src/routes/api/audit/users/+server.ts`

## auth

### `GET, POST` `/auth/ldap`
@openapi summary: List all configured LDAP providers (enterprise only; bind passwords are masked) resp-200: array<{id:integer!, name:string!, enabled:boolean!, serverUrl:string!, baseDn:string!}> resp-200-example: [{"id":1,"name":"Corporate LDAP","enabled":true,"serverUrl":"ldaps://ldap.example.com:636","baseDn":"dc=example,dc=com"}] resp-401: Authentication required (auth is enabled and the caller is not an authenticated admin) resp-403: Enterprise license required resp-500: Failed to read the LDAP configurations
- Source: `src/routes/api/auth/ldap/+server.ts`

### `DELETE, GET, PUT` `/auth/ldap/[id]`
@openapi summary: Get a single LDAP provider configuration by id (enterprise only; bind password is masked) path: id:integer! Numeric id of the LDAP configuration (from GET /api/auth/ldap) resp-200: {id:integer!, name:string!, enabled:boolean!, serverUrl:string!, baseDn:string!} resp-400: Invalid id (not a number) resp-401: Authentication required (auth is enabled and the caller is not an authenticated admin) resp-403: Enterprise license required resp-404: LDAP configuration not found resp-500: Failed to read the LDAP configuration
- Source: `src/routes/api/auth/ldap/[id]/+server.ts`

### `POST` `/auth/ldap/[id]/test`
@openapi summary: Test connectivity of a stored LDAP configuration by id (enterprise only) path: id:integer! Numeric id of the LDAP configuration to test (from GET /api/auth/ldap) resp-200: Connection test result (success flag plus diagnostic detail from the LDAP server) resp-400: Invalid id (not a number) resp-401: Authentication required (auth is enabled and the caller is not an authenticated admin) resp-403: Enterprise license required resp-404: LDAP configuration not found resp-500: Failed to test the LDAP connection
- Source: `src/routes/api/auth/ldap/[id]/test/+server.ts`

### `POST` `/auth/login`
- Source: `src/routes/api/auth/login/+server.ts`

### `POST` `/auth/logout`
@openapi summary: Destroy the current session (clears the dockhand_session cookie) resp-200: {success:boolean!} resp-200-example: {"success":true} resp-500: Unexpected error while destroying the session
- Source: `src/routes/api/auth/logout/+server.ts`

### `GET, POST` `/auth/oidc`
@openapi summary: List all configured OIDC providers (client secrets are masked) resp-200: array<{id:integer!, name:string!, enabled:boolean!, issuerUrl:string!, clientId:string!}> resp-200-example: [{"id":1,"name":"Authentik","enabled":true,"issuerUrl":"https://auth.example.com/application/o/dockhand/","clientId":"dockhand"}] resp-401: Authentication required (auth is enabled and the caller is not authenticated) resp-403: Permission denied (missing settings:view) resp-500: Failed to read the OIDC configurations
- Source: `src/routes/api/auth/oidc/+server.ts`

### `DELETE, GET, PUT` `/auth/oidc/[id]`
@openapi summary: Get a single OIDC provider configuration by id (client secret is masked) path: id:integer! Numeric id of the OIDC configuration (from GET /api/auth/oidc) resp-200: {id:integer!, name:string!, enabled:boolean!, issuerUrl:string!, clientId:string!} resp-400: Invalid configuration id (not a number) resp-401: Authentication required (auth is enabled and the caller is not authenticated) resp-403: Permission denied (missing settings:view) resp-404: OIDC configuration not found resp-500: Failed to read the OIDC configuration
- Source: `src/routes/api/auth/oidc/[id]/+server.ts`

### `GET, POST` `/auth/oidc/[id]/initiate`
@openapi summary: Start the OIDC login flow for a provider — on success throws a 302 redirect to the IdP authorization URL path: id:integer! Numeric id of the OIDC provider (from GET /api/auth/oidc) query: redirect:string Post-login destination path to return to (defaults to /) resp-302: Redirect to the IdP's authorization URL resp-400: Authentication is not enabled, or the configuration id is invalid resp-404: OIDC provider not found or disabled resp-500: Failed to build the authorization URL / initiate SSO
- Source: `src/routes/api/auth/oidc/[id]/initiate/+server.ts`

### `POST` `/auth/oidc/[id]/test`
@openapi summary: Test the discovery/connection of a stored OIDC configuration by id path: id:integer! Numeric id of the OIDC configuration to test (from GET /api/auth/oidc) resp-200: Connection test result (success flag plus diagnostic detail from the provider) resp-400: Invalid configuration id (not a number) resp-403: Admin access required (auth is enabled and the caller is not an admin) resp-500: Failed to test the OIDC connection
- Source: `src/routes/api/auth/oidc/[id]/test/+server.ts`

### `GET` `/auth/oidc/callback`
- Source: `src/routes/api/auth/oidc/callback/+server.ts`

### `GET` `/auth/providers`
@openapi summary: List the authentication providers offered on the login page (local, LDAP, OIDC), plus the default provider resp-200: {providers:array<{id:string!, name:string!, type:string!, initiateUrl:string}>, defaultProvider:string} resp-200-example: {"providers":[{"id":"local","name":"Local","type":"local"},{"id":"oidc:1","name":"Authentik","type":"oidc","initiateUrl":"/api/auth/oidc/1/initiate"}],"defaultProvider":"local"}
- Source: `src/routes/api/auth/providers/+server.ts`

### `GET` `/auth/session`
@openapi summary: Get the current session (public — used by the frontend to bootstrap auth state) resp-200: {authenticated:boolean!, authEnabled:boolean!, user:{id:integer, username:string, email:string, displayName:string, avatar:string, isAdmin:boolean, provider:string}} resp-200-desc: user is present only when authenticated:true resp-200-example: {"authenticated":true,"authEnabled":true,"user":{"id":1,"username":"admin","email":"admin@example.com","displayName":"Admin","avatar":null,"isAdmin":true,"provider":"local"}} resp-500: Unexpected error while validating the session
- Source: `src/routes/api/auth/session/+server.ts`

### `GET, PUT` `/auth/settings`
@openapi summary: Get the global authentication settings (whether auth is enabled and the default provider) resp-200: {authEnabled:boolean!, defaultProvider:string} resp-200-example: {"authEnabled":true,"defaultProvider":"local"} resp-401: Authentication required (auth is enabled and the caller is not authenticated) resp-403: Permission denied (missing settings:view) resp-500: Failed to read the auth settings
- Source: `src/routes/api/auth/settings/+server.ts`

### `GET, POST` `/auth/tokens`
- Source: `src/routes/api/auth/tokens/+server.ts`

### `DELETE` `/auth/tokens/[id]`
DELETE /api/auth/tokens/[id] - Revoke an API token @openapi summary: Revoke (permanently delete) one of the authenticated user's API tokens path: id:integer! Token id (from GET /api/auth/tokens) resp-200: {success:boolean!} resp-200-example: {"success":true} resp-400: Authentication not enabled, or id is not a valid integer resp-401: Not authenticated resp-403: Attempted via Bearer auth (a leaked token cannot revoke other tokens — session required) resp-404: Token not found, or belongs to a different (non-admin) user
- Source: `src/routes/api/auth/tokens/[id]/+server.ts`

## auto-update

### `GET` `/auto-update`
Batch endpoint to get all auto-update settings for an environment. Returns a map of containerName -> settings for efficient lookup. @openapi summary: Get all enabled auto-update settings for an environment, keyed by container name query: env:integer Environment ID to read settings for (from GET /api/environments) resp-200: {} resp-200-example: {"web-1":{"enabled":true,"scheduleType":"daily","cronExpression":"0 3 * * *","vulnerabilityCriteria":"never"}} resp-500: Failed to get auto-update settings
- Source: `src/routes/api/auto-update/+server.ts`

### `DELETE, GET, POST` `/auto-update/[containerName]`
@openapi summary: Get the auto-update setting for a container (returns sensible defaults when none is stored) path: containerName:string! Container name (URL-encoded) query: env:integer Environment the container belongs to (from GET /api/environments) resp-200: {enabled:boolean!, scheduleType:string!, cronExpression:string, vulnerabilityCriteria:string!} resp-200-example: {"enabled":false,"scheduleType":"daily","cronExpression":"0 3 * * *","vulnerabilityCriteria":"never"} resp-500: Failed to get auto-update setting
- Source: `src/routes/api/auto-update/[containerName]/+server.ts`

## backup

### `GET, POST` `/backup/configs`
- Source: `src/routes/api/backup/configs/+server.ts`

### `DELETE, GET, PUT` `/backup/configs/[id]`
- Source: `src/routes/api/backup/configs/[id]/+server.ts`

### `POST` `/backup/configs/[id]/run`
POST /api/backup/configs/{id}/run - Run a backup now (streamed job) @openapi summary: Trigger a manual backup run for a configuration, streaming progress as a Server-Sent Events job description: Returns a text/event-stream that emits `progress` events during the run and a final `result` event. Permission ("backups:manage") and environment-access denials (403) and not-found (404) are produced by the shared route guards. path: id:integer! Backup configuration id (from GET /api/backup/configs) resp-200: Server-Sent Events stream of progress and a final result event (status "success", "warning", "skipped" or "error")
- Source: `src/routes/api/backup/configs/[id]/run/+server.ts`

### `POST` `/backup/configs/[id]/stop`
POST /api/backup/configs/{id}/stop - Cancel a running backup @openapi summary: Cancel the in-flight backup for a configuration description: Permission ("backups:manage") and environment-access denials (403) and not-found (404) are produced by the shared route guards. path: id:integer! Backup configuration id (from GET /api/backup/configs) resp-200: Returns { success: true, stopped } where "stopped" indicates whether a running backup helper was actually killed resp-200-example: {"success":true,"stopped":true} resp-500: Failed to cancel the backup (internal error)
- Source: `src/routes/api/backup/configs/[id]/stop/+server.ts`

### `GET, POST` `/backup/destinations`
- Source: `src/routes/api/backup/destinations/+server.ts`

### `DELETE, GET, PUT` `/backup/destinations/[id]`
- Source: `src/routes/api/backup/destinations/[id]/+server.ts`

### `POST` `/backup/destinations/[id]/init`
- Source: `src/routes/api/backup/destinations/[id]/init/+server.ts`

### `POST` `/backup/destinations/[id]/rotate-key`
Rotate the restic repository password for a destination. @openapi summary: Rotate the restic repository password for a destination and persist the new password description: Permission denial (403, "backups:manage") is produced by the shared requireBackups route guard. path: id:integer! Backup destination id (from GET /api/backup/destinations) body: {currentPassword:string!, newPassword:string!} body-example: {"currentPassword":"***","newPassword":"***"} resp-200: Returns { success: true } once the password is rotated and the database is updated resp-200-example: {"success":true} resp-400: Invalid input — invalid id, missing passwords, or the current password is incorrect resp-404: Destination not found resp-409: restic rotated the key but the database write failed (manual recovery needed; the response includes dbOutOfSync:true) resp-500: restic call failed for an unrelated reason
- Source: `src/routes/api/backup/destinations/[id]/rotate-key/+server.ts`

### `POST` `/backup/destinations/[id]/task`
- Source: `src/routes/api/backup/destinations/[id]/task/+server.ts`

### `POST` `/backup/destinations/[id]/test`
POST /api/backup/destinations/{id}/test - Test a saved backup destination @openapi summary: Test connectivity to a saved backup destination's repository and update its stored test status description: Permission denial (403, "backups:manage") is produced by the shared requireBackups route guard. path: id:integer! Backup destination id (from GET /api/backup/destinations) resp-200: Test result — { success: true, status: "success" } when reachable, or { success: false, status: "needs_init" | "failed", error } otherwise resp-200-example: {"success":true,"status":"success"} resp-400: Invalid id (not a number) resp-404: Destination not found
- Source: `src/routes/api/backup/destinations/[id]/test/+server.ts`

### `POST` `/backup/destinations/[id]/verify`
- Source: `src/routes/api/backup/destinations/[id]/verify/+server.ts`

### `POST` `/backup/destinations/test`
- Source: `src/routes/api/backup/destinations/test/+server.ts`

### `GET` `/backup/instance`
- Source: `src/routes/api/backup/instance/+server.ts`

### `POST` `/backup/restore`
- Source: `src/routes/api/backup/restore/+server.ts`

### `POST` `/backup/restore/preview`
- Source: `src/routes/api/backup/restore/preview/+server.ts`

### `POST` `/backup/restore/stop`
Cancel a running restore (audit #14). Restore was previously uncancellable — the helper container was never targeted by any stop path. Kills the restore helper for the given snapshotId (or all restore helpers if omitted) so restic exits and runRestore's failure/cleanup path runs. @openapi summary: Cancel a running restore — kills the restore helper for a given snapshotId, or all restore helpers when snapshotId is omitted description: snapshotId from GET /api/backup/snapshots. environmentId from GET /api/environments. body: {snapshotId:string, environmentId:integer} body-example: {"snapshotId":"a1b2c3d4"} resp-200: Returns { success: true, stopped } where "stopped" indicates whether a running restore helper was actually killed resp-200-example: {"success":true,"stopped":true} resp-400: Invalid snapshotId resp-403: Permission denied — requires "backups:manage", or no access to the targeted environment resp-500: Failed to cancel the restore (internal error)
- Source: `src/routes/api/backup/restore/stop/+server.ts`

### `GET` `/backup/snapshots`
- Source: `src/routes/api/backup/snapshots/+server.ts`

### `DELETE` `/backup/snapshots/[id]`
- Source: `src/routes/api/backup/snapshots/[id]/+server.ts`

### `GET` `/backup/snapshots/[id]/browse`
- Source: `src/routes/api/backup/snapshots/[id]/browse/+server.ts`

### `GET` `/backup/snapshots/[id]/dump`
- Source: `src/routes/api/backup/snapshots/[id]/dump/+server.ts`

### `GET` `/backup/snapshots/[id]/metadata`
- Source: `src/routes/api/backup/snapshots/[id]/metadata/+server.ts`

### `GET` `/backup/snapshots/diff`
- Source: `src/routes/api/backup/snapshots/diff/+server.ts`

### `GET` `/backup/stack-dir-listing`
- Source: `src/routes/api/backup/stack-dir-listing/+server.ts`

### `GET` `/backup/stack-path`
- Source: `src/routes/api/backup/stack-path/+server.ts`

## batch

### `POST` `/batch`
- Local interfaces: `BatchStartEvent`, `BatchProgressEvent`, `BatchCompleteEvent`, `BatchErrorEvent`, `BatchRequest`
- Source: `src/routes/api/batch/+server.ts`

## changelog

### `GET` `/changelog`
GET /api/changelog - Dockhand changelog @openapi summary: Return the bundled Dockhand changelog data resp-200: array<{version:string!, date:string, changes:array<string>}> resp-200-example: [{"version":"1.0.39","date":"2026-06-01","changes":["Fixed image export streaming"]}]
- Source: `src/routes/api/changelog/+server.ts`

## config-sets

### `GET, POST` `/config-sets`
@openapi summary: List all config sets (reusable bundles of env vars, labels, ports, volumes, and runtime defaults) resp-200: array<{id:integer!, name:string!, description:string, envVars:array<{key:string!, value:string!}>, labels:array<{key:string!, value:string!}>, ports:array<{hostPort:string!, containerPort:string!, protocol:string!}>, volumes:array<{hostPath:string!, containerPath:string!, mode:string!}>, networkMode:string!, restartPolicy:string!, createdAt:string!, updatedAt:string!}> resp-200-example: [{"id":1,"name":"web-defaults","description":"Defaults for web stacks","envVars":[{"key":"TZ","value":"UTC"}],"labels":[],"ports":[],"volumes":[],"networkMode":"bridge","restartPolicy":"unless-stopped","createdAt":"2026-06-01T10:00:00Z","updatedAt":"2026-06-01T10:00:00Z"}] resp-403: Permission denied (requires configsets:view) resp-500: Failed to fetch config sets
- Source: `src/routes/api/config-sets/+server.ts`

### `DELETE, GET, PUT` `/config-sets/[id]`
@openapi summary: Fetch a single config set by its numeric ID path: id:integer! Config set ID (from GET /api/config-sets) resp-200: {id:integer!, name:string!, description:string, envVars:array<{key:string!, value:string!}>, labels:array<{key:string!, value:string!}>, ports:array<{hostPort:string!, containerPort:string!, protocol:string!}>, volumes:array<{hostPath:string!, containerPath:string!, mode:string!}>, networkMode:string!, restartPolicy:string!, createdAt:string!, updatedAt:string!} resp-200-example: {"id":1,"name":"web-defaults","description":"Defaults for web stacks","envVars":[{"key":"TZ","value":"UTC"}],"labels":[],"ports":[],"volumes":[],"networkMode":"bridge","restartPolicy":"unless-stopped","createdAt":"2026-06-01T10:00:00Z","updatedAt":"2026-06-01T10:00:00Z"} resp-400: Invalid ID resp-403: Permission denied (requires configsets:view) resp-404: Config set not found resp-500: Failed to fetch config set
- Source: `src/routes/api/config-sets/[id]/+server.ts`

## container-icons

### `GET` `/container-icons`
@openapi summary: List all container icon overrides for an environment as a name -> icon map description: Returns every container that has a user-set icon override in the given environment, so the containers list can render them in one request instead of one lookup per row. query: env:integer Environment id resp-200: A JSON object mapping container name to its icon value (lucide name, `selfhst:<ref>`, or `custom:container`) resp-200-example: {"plex":"selfhst:plex","db":"custom:container"} resp-403: Permission denied (needs containers:view)
- Source: `src/routes/api/container-icons/+server.ts`

### `DELETE, GET, POST` `/container-icons/[name]`
- Source: `src/routes/api/container-icons/[name]/+server.ts`

## containers

### `GET, POST` `/containers`
- Source: `src/routes/api/containers/+server.ts`

### `DELETE, GET` `/containers/[id]`
- Source: `src/routes/api/containers/[id]/+server.ts`

### `GET` `/containers/[id]/compose`
- Source: `src/routes/api/containers/[id]/compose/+server.ts`

### `POST` `/containers/[id]/exec`
Container Exec API POST: Creates an exec instance for terminal attachment Returns exec ID that can be used for WebSocket connection
- Source: `src/routes/api/containers/[id]/exec/+server.ts`

### `GET` `/containers/[id]/files`
GET /api/containers/{id}/files - List a directory inside a container @openapi summary: List the contents of a directory inside a container's filesystem path: id:string! Container ID or name (from GET /api/containers) query: env:integer The target environment ID (omit for the local/default Docker host) (from GET /api/environments) query: path:string Absolute directory path inside the container (default "/") query: simpleLs:boolean Use a lightweight `ls` listing instead of a full stat of each entry resp-200: Directory listing (entries with name, type, size and permission metadata) resp-403: Permission denied (needs containers:exec) resp-404: Container not found resp-500: Failed to list the directory
- Source: `src/routes/api/containers/[id]/files/+server.ts`

### `POST` `/containers/[id]/files/chmod`
POST /api/containers/{id}/files/chmod - Change permissions of a path in a container @openapi summary: Change the mode (permissions) of a file or directory inside a container (requires the 'exec' permission) path: id:string! Container ID or name (from GET /api/containers) query: env:integer The target environment ID (omit for the local/default Docker host) (from GET /api/environments) body: {path:string!, mode:string!, recursive:boolean} body-example: {"path":"/app/entrypoint.sh","mode":"755","recursive":false} resp-200: {success:boolean!, path:string!, mode:string!, recursive:boolean!} resp-200-example: {"success":true,"path":"/app/entrypoint.sh","mode":"755","recursive":false} resp-400: Path or mode missing, an invalid chmod mode, or the container is not running resp-403: Permission denied, read-only file system, or operation not permitted resp-404: Path not found resp-500: Failed to change permissions
- Source: `src/routes/api/containers/[id]/files/chmod/+server.ts`

### `GET, PUT` `/containers/[id]/files/content`
GET /api/containers/{id}/files/content - Read a file's content from a container @openapi summary: Read the content of a single file inside a container (max 1 MB) path: id:string! Container ID or name (from GET /api/containers) query: env:integer The target environment ID (omit for the local/default Docker host) (from GET /api/environments) query: path:string! Absolute file path inside the container resp-200: {content:string!, path:string!} resp-400: Path is missing, the target is a directory, or the container is not running resp-403: Permission denied to read the file (needs containers:exec) resp-404: File not found resp-413: File is larger than the 1 MB read limit resp-500: Failed to read the file
- Source: `src/routes/api/containers/[id]/files/content/+server.ts`

### `POST` `/containers/[id]/files/create`
POST /api/containers/{id}/files/create - Create a file or directory in a container @openapi summary: Create an empty file or a directory inside a container (requires the 'exec' permission) path: id:string! Container ID or name (from GET /api/containers) query: env:integer The target environment ID (omit for the local/default Docker host) (from GET /api/environments) body: {path:string!, type:string!} body-example: {"path":"/app/data","type":"directory"} resp-200: {success:boolean!, path:string!, type:string!} resp-200-example: {"success":true,"path":"/app/data","type":"directory"} resp-400: Path missing, type not "file" or "directory", or the container is not running resp-403: Permission denied resp-404: Parent directory not found resp-409: Path already exists resp-500: Failed to create the path
- Source: `src/routes/api/containers/[id]/files/create/+server.ts`

### `DELETE` `/containers/[id]/files/delete`
DELETE /api/containers/{id}/files/delete - Delete a path in a container @openapi summary: Delete a file or directory inside a container (requires the 'exec' permission) path: id:string! Container ID or name (from GET /api/containers) query: env:integer The target environment ID (omit for the local/default Docker host) (from GET /api/environments) query: path:string! Absolute path inside the container to delete resp-200: {success:boolean!, path:string!} resp-200-example: {"success":true,"path":"/app/tmp/old.log"} resp-400: Path missing, a refused critical-path delete, a non-empty directory, or the container is not running resp-403: Permission denied, or read-only file system resp-404: Path not found resp-500: Failed to delete the path
- Source: `src/routes/api/containers/[id]/files/delete/+server.ts`

### `GET` `/containers/[id]/files/download`
- Source: `src/routes/api/containers/[id]/files/download/+server.ts`

### `POST` `/containers/[id]/files/rename`
POST /api/containers/{id}/files/rename - Rename/move a path in a container @openapi summary: Rename or move a file or directory inside a container (requires the 'exec' permission) path: id:string! Container ID or name (from GET /api/containers) query: env:integer The target environment ID (omit for the local/default Docker host) (from GET /api/environments) body: {oldPath:string!, newPath:string!} body-example: {"oldPath":"/app/config.yaml","newPath":"/app/config.old.yaml"} resp-200: {success:boolean!, oldPath:string!, newPath:string!} resp-200-example: {"success":true,"oldPath":"/app/config.yaml","newPath":"/app/config.old.yaml"} resp-400: oldPath or newPath missing, or the container is not running resp-403: Permission denied, or read-only file system resp-404: Source path not found resp-409: Destination already exists resp-500: Failed to rename the path
- Source: `src/routes/api/containers/[id]/files/rename/+server.ts`

### `POST` `/containers/[id]/files/upload`
Create a simple tar archive from a single file TAR format: 512-byte header followed by file content padded to 512 bytes
- Source: `src/routes/api/containers/[id]/files/upload/+server.ts`

### `GET` `/containers/[id]/inspect`
- Source: `src/routes/api/containers/[id]/inspect/+server.ts`

### `GET` `/containers/[id]/logs`
GET /api/containers/{id}/logs - Read container logs (non-streaming) @openapi summary: Return the last N lines of a container's combined stdout/stderr logs as a single string path: id:string! Container ID or name (from GET /api/containers) query: env:integer The target environment ID (omit for the local/default Docker host) (from GET /api/environments) query: tail:integer Number of trailing log lines to return (default 100) query: since:string Only return logs since this time (Unix timestamp or Docker duration, e.g. 10m) query: until:string Only return logs before this time (Unix timestamp or Docker duration) resp-200: {logs:string!} resp-403: Permission denied resp-500: Failed to read the container logs
- Source: `src/routes/api/containers/[id]/logs/+server.ts`

### `GET` `/containers/[id]/logs/stream`
- Local interfaces: `DockerClientConfig`
- Source: `src/routes/api/containers/[id]/logs/stream/+server.ts`

### `POST` `/containers/[id]/pause`
POST /api/containers/{id}/pause - Pause a container @openapi summary: Pause all processes in a running container (requires the container 'stop' permission) path: id:string! Container ID or name (from GET /api/containers) query: env:integer The target environment ID (omit for the local/default Docker host) (from GET /api/environments) resp-200: {success:boolean!} resp-200-example: {"success":true} resp-403: Permission denied resp-500: Failed to pause the container
- Source: `src/routes/api/containers/[id]/pause/+server.ts`

### `POST` `/containers/[id]/rename`
POST /api/containers/{id}/rename - Rename a container @openapi summary: Rename a container and update any associated auto-update schedule (requires the 'create' permission) path: id:string! Container ID or name (from GET /api/containers) query: env:integer The target environment ID (omit for the local/default Docker host) (from GET /api/environments) body: {name:string!} body-example: {"name":"my-renamed-container"} resp-200: {success:boolean!} resp-200-example: {"success":true} resp-400: The new name is missing or not a string resp-403: Permission denied resp-404: Container not found resp-500: Failed to rename the container
- Source: `src/routes/api/containers/[id]/rename/+server.ts`

### `POST` `/containers/[id]/restart`
POST /api/containers/{id}/restart - Restart a container @openapi summary: Restart a container path: id:string! Container ID or name (from GET /api/containers) query: env:integer The target environment ID (omit for the local/default Docker host) (from GET /api/environments) resp-200: {success:boolean!} resp-200-example: {"success":true} resp-403: Permission denied, or (enterprise) no access to the requested environment resp-404: Container not found resp-500: Failed to restart the container
- Source: `src/routes/api/containers/[id]/restart/+server.ts`

### `GET` `/containers/[id]/shells`
- Source: `src/routes/api/containers/[id]/shells/+server.ts`

### `POST` `/containers/[id]/start`
POST /api/containers/{id}/start - Start a container @openapi summary: Start a stopped container path: id:string! Container ID or name (from GET /api/containers) query: env:integer The target environment ID (omit for the local/default Docker host) (from GET /api/environments) resp-200: {success:boolean!} resp-200-example: {"success":true} resp-403: Permission denied, or (enterprise) no access to the requested environment resp-404: Container not found resp-500: Failed to start the container
- Source: `src/routes/api/containers/[id]/start/+server.ts`

### `GET` `/containers/[id]/stats`
- Source: `src/routes/api/containers/[id]/stats/+server.ts`

### `POST` `/containers/[id]/stop`
POST /api/containers/{id}/stop - Stop a container @openapi summary: Stop a running container path: id:string! Container ID or name (from GET /api/containers) query: env:integer The target environment ID (omit for the local/default Docker host) (from GET /api/environments) resp-200: {success:boolean!} resp-200-example: {"success":true} resp-403: Permission denied, or (enterprise) no access to the requested environment resp-404: Container not found resp-500: Failed to stop the container
- Source: `src/routes/api/containers/[id]/stop/+server.ts`

### `GET` `/containers/[id]/top`
- Source: `src/routes/api/containers/[id]/top/+server.ts`

### `POST` `/containers/[id]/unpause`
POST /api/containers/{id}/unpause - Unpause a container @openapi summary: Resume all processes in a paused container (requires the container 'start' permission) path: id:string! Container ID or name (from GET /api/containers) query: env:integer The target environment ID (omit for the local/default Docker host) (from GET /api/environments) resp-200: {success:boolean!} resp-200-example: {"success":true} resp-403: Permission denied resp-500: Failed to unpause the container
- Source: `src/routes/api/containers/[id]/unpause/+server.ts`

### `POST` `/containers/[id]/update`
- Source: `src/routes/api/containers/[id]/update/+server.ts`

### `POST` `/containers/[id]/update-runtime`
POST /api/containers/[id]/update-runtime In-place update of a running container's restart policy, CPU/memory limits, blkio weights, and pids limit — the only properties Docker can change without recreating the container. The body must contain ONLY fields from IN_PLACE_UPDATE_FIELDS (see docker.ts); any unknown fields are silently dropped so a confused or malicious caller can't sneak a recreate-only field (image, env, ports, etc.) through this path. Returns Docker's response — typically `{ Warnings: string[] | null }`.
- Source: `src/routes/api/containers/[id]/update-runtime/+server.ts`

### `GET` `/containers/[id]/version-notes`
- Source: `src/routes/api/containers/[id]/version-notes/+server.ts`

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
Get pending container updates for an environment. @openapi summary: List the containers in an environment that have a pending image update recorded (requires the 'view' permission) query: env:integer! The target environment ID (required) (from GET /api/environments) resp-200: {environmentId:integer!, pendingUpdates:array<{containerId:string!, containerName:string!, currentImage:string!, checkedAt:string!, hasImageUpdate:boolean!, newerVersion:object}>!} resp-400: Environment ID is required resp-403: Permission denied resp-500: Failed to get the pending updates
- Source: `src/routes/api/containers/pending-updates/+server.ts`

### `GET` `/containers/sizes`
GET /api/containers/sizes - List containers with their on-disk sizes @openapi summary: List all containers in an environment together with their writable-layer and root-filesystem sizes (requires the 'view' permission) query: env:integer The target environment ID (omit for the local/default Docker host) (from GET /api/environments) resp-200: Array of containers with size metadata (SizeRw / SizeRootFs) resp-403: Permission denied resp-500: Failed to get container sizes (returns an empty object)
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

## docs

### `GET` `/docs`
- Source: `src/routes/api/docs/+server.ts`

## environments

### `GET, POST` `/environments`
- Source: `src/routes/api/environments/+server.ts`

### `DELETE, GET, PUT` `/environments/[id]`
- Source: `src/routes/api/environments/[id]/+server.ts`

### `GET, POST` `/environments/[id]/disk-warning`
@openapi summary: Get the disk-space warning thresholds for an environment path: id:integer! Environment id (from GET /api/environments) resp-200: {enabled:boolean!, mode:string!, threshold:integer!, thresholdGb:integer!} resp-200-example: {"enabled":true,"mode":"percentage","threshold":80,"thresholdGb":50} resp-403: Permission denied (RBAC 'environments:view' missing) resp-404: Environment not found resp-500: Unexpected error while loading the settings
- Source: `src/routes/api/environments/[id]/disk-warning/+server.ts`

### `DELETE, GET, POST` `/environments/[id]/icon`
@openapi summary: Get the custom icon image for an environment (raw image/webp bytes, not JSON) path: id:integer! Environment id (from GET /api/environments) resp-200: Binary image/webp response body, Cache-Control public max-age=3600 resp-404: No custom icon set for this environment
- Source: `src/routes/api/environments/[id]/icon/+server.ts`

### `GET, POST, PUT` `/environments/[id]/image-prune`
Get image prune settings for an environment. @openapi summary: Get the automatic image-prune schedule settings for an environment path: id:integer! Environment id (from GET /api/environments) resp-200: {settings:{enabled:boolean!, cronExpression:string!, pruneMode:string!}!} resp-200-example: {"settings":{"enabled":false,"cronExpression":"0 3 * * 0","pruneMode":"dangling"}} resp-403: Permission denied (RBAC 'environments:view' missing) resp-404: Environment not found resp-500: Unexpected error while loading the settings
- Source: `src/routes/api/environments/[id]/image-prune/+server.ts`

### `GET, POST` `/environments/[id]/notifications`
- Source: `src/routes/api/environments/[id]/notifications/+server.ts`

### `DELETE, GET, PUT` `/environments/[id]/notifications/[notificationId]`
- Source: `src/routes/api/environments/[id]/notifications/[notificationId]/+server.ts`

### `GET, POST` `/environments/[id]/remote-stacks-dir`
- Source: `src/routes/api/environments/[id]/remote-stacks-dir/+server.ts`

### `POST` `/environments/[id]/test`
- Source: `src/routes/api/environments/[id]/test/+server.ts`

### `GET, POST` `/environments/[id]/timezone`
Map of modern IANA timezone names to their canonical equivalents recognized by ICU
- Source: `src/routes/api/environments/[id]/timezone/+server.ts`

### `GET, POST` `/environments/[id]/update-check`
Get update check settings for an environment. @openapi summary: Get the automatic container-image update-check schedule for an environment path: id:integer! Environment id (from GET /api/environments) resp-200: {settings:{enabled:boolean!, cron:string!, autoUpdate:boolean!, vulnerabilityCriteria:string!}!} resp-200-example: {"settings":{"enabled":false,"cron":"0 4 * * *","autoUpdate":false,"vulnerabilityCriteria":"never"}} resp-403: Permission denied (RBAC 'environments:view' missing) resp-404: Environment not found resp-500: Unexpected error while loading the settings
- Source: `src/routes/api/environments/[id]/update-check/+server.ts`

### `GET` `/environments/detect-socket`
Detect available Docker sockets on the system @openapi summary: Detect common Docker/Podman socket paths that exist on the Dockhand host resp-200: {sockets:array<{path:string!, name:string!, exists:boolean!}>!, homedir:string!} resp-200-example: {"sockets":[{"path":"/var/run/docker.sock","name":"Docker (default)","exists":true}],"homedir":"/home/dockhand"}
- Local interfaces: `DetectedSocket`
- Source: `src/routes/api/environments/detect-socket/+server.ts`

### `POST` `/environments/test`
- Local interfaces: `TestConnectionRequest`
- Source: `src/routes/api/environments/test/+server.ts`

## events

### `GET` `/events`
@openapi summary: Stream live Docker events (container/image/volume/network) for an environment via SSE, with periodic heartbeats query: env:integer Environment id — without it, an "info" SSE message is sent and the stream ends (from GET /api/environments) resp-200: text/event-stream SSE stream ("connected", "heartbeat" every 5s, "docker" events with {type,action,actor,time,timeNano}, or an "error"/"info" event for edge environments, missing/unknown environment, or a lost Docker connection)
- Source: `src/routes/api/events/+server.ts`

## git

### `POST` `/git/branches`
POST /api/git/branches List remote branches for a repository via `git ls-remote`. SECURITY: assertSafeRepoTarget runs before any git subprocess is spawned — the shared SSRF policy (delegated to isSafeNotificationUrl, src/lib/server/url-safety.ts): loopback, link-local / cloud-metadata and other reserved/dangerous targets are rejected, while ordinary private-LAN addresses are INTENTIONALLY ALLOWED so self-hosted Git servers on RFC1918 ranges (10.x / 192.168.x / 172.16-31.x) keep working. Runs on BOTH the `url` and `repositoryId` paths (a stored repository's URL could also point internal). The `ls-remote` itself is bounded by a hard timeout (see listRemoteBranches in src/lib/server/git.ts) — clone/pull/fetch stay unbounded. Body: {   repositoryId?: number,     // Existing repository (uses its url + credential)   url?: string,              // OR a new repository URL   credentialId?: number|null // Credential for the url (new-repo flow) } Returns: { branches: { name: string, sha: string }[] }
- Source: `src/routes/api/git/branches/+server.ts`

### `GET, POST` `/git/credentials`
@openapi summary: List all stored git credentials with secrets stripped (only hasPassword/hasSshKey flags returned) resp-200: array<{id:integer!, name:string!, authType:string!, username:string, hasPassword:boolean!, hasSshKey:boolean!, createdAt:string, updatedAt:string}> resp-200-example: [{"id":1,"name":"github-deploy","authType":"ssh","username":"git","hasPassword":false,"hasSshKey":true,"createdAt":"2026-06-01T10:00:00Z","updatedAt":"2026-06-01T10:00:00Z"}] resp-403: Caller lacks the git:view permission resp-500: Failed to read git credentials from the database
- Source: `src/routes/api/git/credentials/+server.ts`

### `DELETE, GET, PUT` `/git/credentials/[id]`
@openapi summary: Get a single git credential by ID with secrets stripped (only hasPassword/hasSshKey flags returned) path: id:integer! Git credential ID (from GET /api/git/credentials) resp-200: {id:integer!, name:string!, authType:string!, username:string, hasPassword:boolean!, hasSshKey:boolean!, createdAt:string, updatedAt:string} resp-400: The id path segment is not a valid integer resp-403: Caller lacks the git:view permission resp-404: No credential exists with that ID resp-500: Failed to read the git credential
- Source: `src/routes/api/git/credentials/[id]/+server.ts`

### `POST` `/git/preview-env`
- Source: `src/routes/api/git/preview-env/+server.ts`

### `GET, POST` `/git/repositories`
@openapi summary: List all git repositories (repositories are global, not scoped to an environment) resp-200: array<{id:integer!, name:string!, url:string!, branch:string!, credentialId:integer}> resp-200-example: [{"id":1,"name":"homelab","url":"https://github.com/example/homelab.git","branch":"main","credentialId":2}] resp-403: Caller lacks the git:view permission resp-500: Failed to read git repositories
- Source: `src/routes/api/git/repositories/+server.ts`

### `DELETE, GET, PUT` `/git/repositories/[id]`
- Source: `src/routes/api/git/repositories/[id]/+server.ts`

### `POST` `/git/repositories/[id]/deploy`
@openapi summary: Deploy the compose stack(s) defined in a git repository (clones/pulls, then runs docker compose) path: id:integer! Git repository ID (from GET /api/git/repositories) resp-200: {success:boolean!, error:string} resp-200-example: {"success":true} resp-400: The id path segment is not a valid integer resp-403: Caller lacks the git:edit permission resp-404: No repository exists with that ID resp-500: The deployment failed
- Source: `src/routes/api/git/repositories/[id]/deploy/+server.ts`

### `GET, POST` `/git/repositories/[id]/sync`
@openapi summary: Sync (git pull) the local clone of a repository to the latest commit on its tracked branch path: id:integer! Git repository ID (from GET /api/git/repositories) resp-200: {success:boolean!, error:string} resp-200-example: {"success":true} resp-400: The id path segment is not a valid integer resp-403: Caller lacks the git:edit permission resp-404: No repository exists with that ID resp-500: The sync failed
- Source: `src/routes/api/git/repositories/[id]/sync/+server.ts`

### `POST` `/git/repositories/[id]/test`
@openapi summary: Test connectivity/authentication to a saved repository using its stored credential path: id:integer! Git repository ID (from GET /api/git/repositories) resp-200: {success:boolean!, error:string} resp-200-example: {"success":true} resp-400: The id path segment is not a valid integer resp-403: Caller lacks the git:edit permission resp-404: No repository exists with that ID resp-500: The connectivity test failed
- Source: `src/routes/api/git/repositories/[id]/test/+server.ts`

### `POST` `/git/repositories/test`
POST /api/git/repositories/test Test a git repository configuration before saving. Uses stored credentials via credentialId. Body: {   url: string;           // Repository URL to test   branch: string;        // Branch name to verify   credentialId?: number; // Optional credential ID from database }
- Source: `src/routes/api/git/repositories/test/+server.ts`

### `GET, POST` `/git/stacks`
- Source: `src/routes/api/git/stacks/+server.ts`

### `DELETE, GET, PUT` `/git/stacks/[id]`
- Source: `src/routes/api/git/stacks/[id]/+server.ts`

### `POST` `/git/stacks/[id]/deploy`
@openapi summary: Deploy a git stack, streaming the deploy log as SSE result events via the job-response channel path: id:integer! Git stack ID (from GET /api/git/stacks) resp-200: {} resp-200-desc: An SSE stream whose final `result` event carries {success, error} resp-403: Caller lacks the stacks:start permission for the stack's environment resp-404: No git stack exists with that ID resp-500: Failed to start the deployment
- Source: `src/routes/api/git/stacks/[id]/deploy/+server.ts`

### `POST` `/git/stacks/[id]/deploy-stream`
@openapi summary: Deploy a git stack with live progress; streams SSE, or returns a jobId to poll (Accept negotiated) description: Clients sending `Accept: application/json` get a synchronous, buffered SSE-as-JSON result; otherwise a jobId is returned immediately and progress is delivered out-of-band. path: id:integer! Git stack ID (from GET /api/git/stacks) resp-200: {jobId:string} resp-200-desc: Deployment started — either a jobId to poll or a streamed SSE deploy log resp-200-example: {"jobId":"a1b2c3d4"} resp-403: Caller lacks the stacks:start permission for the stack's environment resp-404: No git stack exists with that ID
- Source: `src/routes/api/git/stacks/[id]/deploy-stream/+server.ts`

### `GET, POST` `/git/stacks/[id]/env-files`
GET /api/git/stacks/[id]/env-files List all .env files in the git stack's repository. Returns: { files: string[] }
- Source: `src/routes/api/git/stacks/[id]/env-files/+server.ts`

### `POST` `/git/stacks/[id]/sync`
@openapi summary: Sync (git pull) a git stack's repository clone to the latest tracked commit path: id:integer! Git stack ID (from GET /api/git/stacks) resp-200: {success:boolean!, error:string} resp-200-example: {"success":true} resp-403: Caller lacks the stacks:edit permission for the stack's environment resp-404: No git stack exists with that ID resp-500: The sync failed
- Source: `src/routes/api/git/stacks/[id]/sync/+server.ts`

### `POST` `/git/stacks/[id]/test`
@openapi summary: Test a git stack's repository access and compose configuration without deploying path: id:integer! Git stack ID (from GET /api/git/stacks) resp-200: {success:boolean!, error:string} resp-200-example: {"success":true} resp-403: Caller lacks the stacks:view permission for the stack's environment resp-404: No git stack exists with that ID resp-500: The test failed
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
@openapi summary: Liveness probe — always returns 200 when the SvelteKit process is up resp-200: {status:string!, timestamp:string!} resp-200-example: {"status":"ok","timestamp":"2027-01-01T12:00:00.000Z"}
- Source: `src/routes/api/health/+server.ts`

### `GET` `/health/database`
Database Health Check Endpoint Public endpoint suitable for external monitoring. The public payload reports enough detail to detect schema drift and table loss without exposing connection details (host, port, db name, user) or the running migration tag. Authenticated callers with settings:view get the full payload — connection string (password masked) and schema version included — which is useful for operators debugging from the admin UI. GET /api/health/database
- Source: `src/routes/api/health/database/+server.ts`

## host

### `GET` `/host`
- Local interfaces: `HostInfo`
- Source: `src/routes/api/host/+server.ts`

## icons

### `GET` `/icons/selfhst-manifest`
@openapi summary: Get the selfh.st icon manifest (index.json), cached on disk with a 7-day TTL description: Returns the selfh.st collection manifest (~2880 entries with Name, Reference, format flags, Category, Tags) so the icon picker can search it. Fetched once from the CDN and cached under DATA_DIR. Returns 503 only if it has never been fetched and the fetch fails. resp-200: The raw selfh.st index.json array (application/json) resp-503: The manifest is unavailable (never cached and the upstream fetch failed)
- Source: `src/routes/api/icons/selfhst-manifest/+server.ts`

### `GET` `/icons/selfhst/[ref]`
- Source: `src/routes/api/icons/selfhst/[ref]/+server.ts`

### `POST` `/icons/selfhst/batch`
POST /api/icons/selfhst/batch - resolve many selfh.st icons in ONE request. The icon picker renders a grid of app logos; fetching each as its own <img src="/api/icons/selfhst/<ref>"> makes dozens of distinct requests in a second, which a WAF (CrowdSec) flags as crawling/probing and blocks the client (#1467). This batches them: the client asks for all visible refs at once and gets one response, so the WAF sees a single request. Refs that can't be resolved are simply omitted (no per-icon 404s, which also read as probing). Each icon is returned as a `data:image/svg+xml` URI so the picker keeps rendering via <img> (script-inert) rather than inlining SVG markup - the SVG sanitizer was designed for the <img>+CSP path, so we don't weaken it by switching to {@html}. @openapi summary: Resolve multiple selfh.st app icons in one request (avoids per-icon requests a WAF flags as crawling) description: Takes a list of selfh.st icon references and returns each resolved icon as a data:image/svg+xml URI, keyed by reference. Unresolvable or invalid refs are omitted rather than returned as errors. Each icon is fetched from the CDN once and cached on disk, same as the single-icon endpoint. body: {refs:array<string>!} body-example: {"refs":["plex","gitea","grafana"]} resp-200: {icons:object!} resp-200-desc: icons maps each resolved reference to a data:image/svg+xml base64 URI; unresolvable refs are omitted. resp-200-example: {"icons":{"plex":"data:image/svg+xml;base64,PHN2Zy4uLg=="}} resp-400: The request body is missing a refs array
- Source: `src/routes/api/icons/selfhst/batch/+server.ts`

## images

### `GET` `/images`
GET /api/images - List Docker images for an environment @openapi summary: List the Docker images of an environment (returns an empty array when no env is given or Docker is unreachable) query: env:integer ID of the environment whose images to list (from GET /api/environments) resp-200: array<{Id:string!, RepoTags:array<string>, Size:integer, Created:integer}> resp-200-desc: Array of images (empty if no env is specified or the Docker connection fails) resp-200-example: [{"Id":"sha256:abc123","RepoTags":["nginx:latest"],"Size":142000000,"Created":1719830400}] resp-403: Permission denied, or (enterprise) no access to this environment resp-404: Environment not found
- Source: `src/routes/api/images/+server.ts`

### `DELETE` `/images/[id]`
DELETE /api/images/{id} - Remove a Docker image @openapi summary: Remove a Docker image by ID or name (optionally forced), scoped to an environment path: id:string! Image ID or name to remove (from GET /api/images) query: env:integer ID of the environment the image belongs to (from GET /api/environments) query: force:boolean Force removal even if the image is tagged or referenced (default false) resp-200: {success:boolean!} resp-200-example: {"success":true} resp-403: Permission denied, or (enterprise) no access to this environment resp-409: Image is in use by a running container or has dependent child images resp-500: Failed to remove image
- Source: `src/routes/api/images/[id]/+server.ts`

### `GET` `/images/[id]/export`
GET /api/images/{id}/export - Download an image as a tar (optionally gzipped) @openapi summary: Export a Docker image as a downloadable tar (or tar.gz) stream path: id:string! Image ID or name to export (from GET /api/images) query: env:integer ID of the environment the image belongs to (from GET /api/environments) query: compress:boolean Gzip the tar stream and serve it as .tar.gz (default false) resp-200: The image tar (application/x-tar) or gzipped tar (application/gzip) as an attachment resp-403: Permission denied resp-500: Docker returned no response body, or the export failed
- Source: `src/routes/api/images/[id]/export/+server.ts`

### `GET` `/images/[id]/history`
GET /api/images/{id}/history - Layer history of an image @openapi summary: Return the layer build history of a Docker image path: id:string! Image ID or name whose history to return (from GET /api/images) query: env:integer ID of the environment the image belongs to (from GET /api/environments) resp-200: array<{Id:string, Created:integer, CreatedBy:string, Size:integer, Comment:string}> resp-200-example: [{"Id":"sha256:abc123","Created":1719830400,"CreatedBy":"/bin/sh -c #(nop) CMD","Size":0,"Comment":""}] resp-403: Permission denied resp-500: Failed to get image history
- Source: `src/routes/api/images/[id]/history/+server.ts`

### `POST` `/images/[id]/tag`
POST /api/images/{id}/tag - Add a repository tag to an image @openapi summary: Tag a Docker image into a repository (defaults the tag to "latest") path: id:string! Image ID or name to tag (from GET /api/images) query: env:integer ID of the environment the image belongs to (from GET /api/environments) body: {repo:string!, tag:string} body-example: {"repo":"registry.example.com/myapp","tag":"v1.2.3"} resp-200: {success:boolean!} resp-200-example: {"success":true} resp-400: Repository name is missing or not a string resp-403: Permission denied resp-500: Failed to tag image
- Source: `src/routes/api/images/[id]/tag/+server.ts`

### `POST` `/images/load`
POST /api/images/load - load a Docker image from an uploaded tar (docker load), for air-gapped hosts. The request BODY is the raw tar (Content-Type application/x-tar); it is streamed straight to the daemon without buffering, so a large image does not OOM. This is SYNCHRONOUS on purpose - it must NOT use the job-polling pattern. That pattern returns immediately and runs the operation in the background, but the tar lives in the request body, which is torn down once the response is sent; a backgrounded read would hang on a dead stream. So we consume the body and stream it to the daemon while the request is still open, then return the result. Local/socket and direct TCP only (loadImage rejects Hawser). @openapi summary: Load a Docker image from an uploaded tar (docker load) for air-gapped hosts description: The request body is the raw image tar (Content-Type application/x-tar), streamed straight to the daemon without buffering. Local/socket or direct TCP only; Hawser is rejected. body-raw: application/x-tar The raw image tar, streamed to the daemon (docker load) query: env:integer Target environment id resp-200: {success:boolean!, loaded:string} resp-200-desc: loaded echoes the daemon's final line, e.g. "Loaded image: alpine:3.20" resp-400: Request body (an image tar) is required resp-403: Permission denied (needs images:load), or access denied to this environment resp-500: The daemon rejected the tar or the load failed
- Source: `src/routes/api/images/load/+server.ts`

### `POST` `/images/pull`
- Source: `src/routes/api/images/pull/+server.ts`

### `POST` `/images/push`
- Source: `src/routes/api/images/push/+server.ts`

### `GET, POST` `/images/scan`
POST /api/images/scan - Start a vulnerability scan (SSE progress) @openapi summary: Start a vulnerability scan of an image and stream scan progress as Server-Sent Events, persisting the results query: env:integer ID of the environment the image belongs to (from GET /api/environments) body: {imageName:string!, scanner:string} body-example: {"imageName":"nginx:latest","scanner":"grype"} resp-200: A Server-Sent Events stream of scan progress, ending with a "result" event resp-400: Image name is required resp-403: Permission denied
- Source: `src/routes/api/images/scan/+server.ts`

### `GET` `/images/scan/export`
Per-image vulnerability export (#415): reformats the cached scan for one image as json | csv | sarif for CI / DefectDojo / Dependency-Track integration. Read-only over persisted scans; no new scanning. Auth via cookie or Bearer token (CI), with RBAC + enterprise environment scoping.
- Source: `src/routes/api/images/scan/export/+server.ts`

## jobs

### `DELETE, GET` `/jobs/[id]`
GET /api/jobs/[id] Poll a job's status and accumulated lines. Returns all lines every time — client tracks its own cursor locally. Authenticated via the global hook. Only the user who created the job (or an admin) may read it; others get a 404 so a job's existence is not revealed.
- Source: `src/routes/api/jobs/[id]/+server.ts`

## labels

### `GET, POST` `/labels`
- Source: `src/routes/api/labels/+server.ts`

## legal

### `GET` `/legal/license`
@openapi summary: Return the bundled LICENSE.txt — as JSON by default, or as raw text/plain when format=text query: format:string Set to "text" to return the raw license as text/plain instead of JSON resp-200: {content:string!} resp-200-desc: The license text (as {content} JSON, or raw text/plain when format=text) resp-404: LICENSE.txt could not be found/read
- Source: `src/routes/api/legal/license/+server.ts`

### `GET` `/legal/privacy`
@openapi summary: Return the bundled PRIVACY.txt — as JSON by default, or as raw text/plain when format=text query: format:string Set to "text" to return the raw privacy policy as text/plain instead of JSON resp-200: {content:string!} resp-200-desc: The privacy policy text (as {content} JSON, or raw text/plain when format=text) resp-404: PRIVACY.txt could not be found/read
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
@openapi summary: List Docker networks for an environment (returns an empty array when no env is given) query: env:integer Environment ID to list networks from (from GET /api/environments) resp-200: array<{Id:string!, Name:string!, Driver:string, Scope:string, Internal:boolean, Attachable:boolean}> resp-403: Permission denied, or access denied to the requested environment (enterprise) resp-404: Environment not found resp-500: Failed to list networks
- Source: `src/routes/api/networks/+server.ts`

### `DELETE, GET` `/networks/[id]`
@openapi summary: Inspect a Docker network by ID (a malformed ID is rejected with 400 by input validation) path: id:string! Docker network ID (from GET /api/networks) query: env:integer Environment the network belongs to (from GET /api/environments) resp-200: {Id:string!, Name:string!, Driver:string, Scope:string, IPAM:{}, Containers:{}} resp-403: Permission denied, or access denied to the requested environment (enterprise) resp-500: Failed to inspect network
- Source: `src/routes/api/networks/[id]/+server.ts`

### `POST` `/networks/[id]/connect`
@openapi summary: Connect a container to a Docker network description: containerId from GET /api/containers. path: id:string! Docker network ID (from GET /api/networks) query: env:integer Environment the network belongs to (from GET /api/environments) body: {containerId:string!, containerName:string} body-example: {"containerId":"a1b2c3d4e5f6","containerName":"web-1"} resp-200: {success:boolean!} resp-200-example: {"success":true} resp-400: Container ID is required resp-403: Permission denied resp-500: Failed to connect container to network
- Source: `src/routes/api/networks/[id]/connect/+server.ts`

### `POST` `/networks/[id]/disconnect`
@openapi summary: Disconnect a container from a Docker network (optionally forcing the disconnect) description: containerId from GET /api/containers. path: id:string! Docker network ID (from GET /api/networks) query: env:integer Environment the network belongs to (from GET /api/environments) body: {containerId:string!, containerName:string, force:boolean} body-example: {"containerId":"a1b2c3d4e5f6","containerName":"web-1","force":false} resp-200: {success:boolean!} resp-200-example: {"success":true} resp-400: Container ID is required resp-403: Permission denied resp-500: Failed to disconnect container from network
- Source: `src/routes/api/networks/[id]/disconnect/+server.ts`

### `GET` `/networks/[id]/inspect`
@openapi summary: Inspect a Docker network by ID (a malformed ID is rejected with 400 by input validation) path: id:string! Docker network ID (from GET /api/networks) query: env:integer Environment the network belongs to (from GET /api/environments) resp-200: {Id:string!, Name:string!, Driver:string, Scope:string, IPAM:{}, Containers:{}} resp-403: Permission denied resp-500: Failed to inspect network
- Source: `src/routes/api/networks/[id]/inspect/+server.ts`

## notifications

### `GET, POST` `/notifications`
@openapi summary: List all notification settings (SMTP and Apprise) with SMTP passwords masked resp-200: array<{id:integer!, type:string!, name:string!, enabled:boolean!, config:{host:string, port:integer, from_email:string, to_emails:array<string>, urls:array<string>, password:string}, eventTypes:array<string>}> resp-403: Permission denied (requires the notifications:view permission when auth is enabled) resp-500: Failed to fetch notification settings
- Source: `src/routes/api/notifications/+server.ts`

### `DELETE, GET, PUT` `/notifications/[id]`
- Source: `src/routes/api/notifications/[id]/+server.ts`

### `POST` `/notifications/[id]/test`
@openapi summary: Send a test notification through an already-saved notification setting path: id:integer! Notification setting ID (from GET /api/notifications) resp-200: {success:boolean!, message:string, error:string} resp-200-example: {"success":true,"message":"Test notification sent successfully"} resp-400: Invalid ID (not a number) resp-403: Permission denied (needs notifications:edit) resp-404: Notification setting not found resp-500: Failed to test notification
- Source: `src/routes/api/notifications/[id]/test/+server.ts`

### `POST` `/notifications/test`
@openapi summary: Send a test notification using an ad-hoc config supplied in the body (nothing is saved) body: {type:string!, name:string, config:{host:string, port:integer, secure:boolean, username:string, password:string, from_email:string, from_name:string, to_emails:array<string>, urls:array<string>}} body-example: {"type":"smtp","name":"Test","config":{"host":"smtp.example.com","port":587,"from_email":"dockhand@example.com","to_emails":["ops@example.com"],"password":"***"}} resp-200: {success:boolean!, message:string, error:string} resp-200-example: {"success":true,"message":"Test notification sent successfully"} resp-400: Missing/invalid fields — type and config required; SMTP needs host/from_email/to_emails; Apprise needs at least one URL resp-403: Permission denied (requires the settings:edit permission) resp-500: Failed to test notification
- Source: `src/routes/api/notifications/test/+server.ts`

### `GET, POST` `/notifications/trigger-test`
Test endpoint to trigger notifications for any event type. This is intended for development/testing purposes only. @openapi summary: Trigger a real notification for a given event type (development/testing helper) description: environmentId from GET /api/environments. body: {eventType:string!, environmentId:integer, payload:{title:string!, message:string!, type:string}} body-example: {"eventType":"container_unhealthy","environmentId":1,"payload":{"title":"Container unhealthy","message":"web-1 is unhealthy","type":"warning"}} resp-200: {success:boolean!, sent:integer, eventType:string!, environmentId:integer} resp-200-example: {"success":true,"sent":1,"eventType":"container_unhealthy","environmentId":1} resp-400: eventType required, payload with title and message required, unknown event type, or environmentId missing for a non-system event resp-500: Unknown error while sending the notification
- Source: `src/routes/api/notifications/trigger-test/+server.ts`

## preferences

### `GET, POST` `/preferences/favorite-groups`
- Local interfaces: `FavoriteGroup`
- Source: `src/routes/api/preferences/favorite-groups/+server.ts`

### `GET, POST` `/preferences/favorites`
@openapi summary: Get the saved log favorites (container names) for an environment query: env:integer! Environment ID (from GET /api/environments) resp-200: {favorites:array<string>} resp-200-example: {"favorites":["web-1","db-1"]} resp-400: Environment ID is required, or invalid (not a number) resp-500: Failed to get favorites
- Source: `src/routes/api/preferences/favorites/+server.ts`

### `DELETE, GET, POST` `/preferences/grid`
@openapi summary: Retrieve all saved data-grid column preferences (per-user when auth is enabled) resp-200: {preferences:{}} resp-200-example: {"preferences":{"containers":{"columns":[{"id":"name","visible":true}]}}} resp-500: Failed to get grid preferences
- Source: `src/routes/api/preferences/grid/+server.ts`

### `DELETE, GET, POST` `/preferences/sidebar`
@openapi summary: Retrieve the saved sidebar menu preferences (order and hidden items) resp-200: {preferences:{order:array<string>, hidden:array<string>}} resp-200-example: {"preferences":{"order":["dashboard","containers"],"hidden":["volumes"]}} resp-500: Failed to get sidebar preferences
- Source: `src/routes/api/preferences/sidebar/+server.ts`

## profile

### `GET, PUT` `/profile`
- Source: `src/routes/api/profile/+server.ts`

### `DELETE, POST` `/profile/avatar`
@openapi summary: Upload the authenticated user's avatar as a base64 image data URL (max ~500KB) body: {avatar:string!} body-example: {"avatar":"data:image/png;base64,iVBORw0KGgo..."} resp-200: {success:boolean!, avatar:string!} resp-400: Authentication is not enabled, avatar data missing, not an image data URL, or image too large (>500KB) resp-401: Not authenticated resp-500: Failed to upload the avatar
- Source: `src/routes/api/profile/avatar/+server.ts`

### `GET, PUT` `/profile/preferences`
@openapi summary: Get the current user's UI preferences (theme, fonts, editor options) resp-400: Not authenticated / no user in context resp-401: Not authenticated resp-500: Failed to load preferences
- Source: `src/routes/api/profile/preferences/+server.ts`

## prune

### `POST` `/prune/all`
POST /api/prune/all - Prune every unused Docker resource type at once @openapi summary: Prune all unused Docker resources (containers, images, volumes and networks) in a single operation query: env:integer Target environment id; scopes both the prune operation and the permission check (defaults to the local environment) (from GET /api/environments) resp-200: Returns { success: true, result } where result is the aggregated Docker prune report (space reclaimed, items deleted) resp-200-example: {"success":true,"result":{"ContainersDeleted":["abc123"],"ImagesDeleted":[],"VolumesDeleted":[],"NetworksDeleted":[],"SpaceReclaimed":10485760}} resp-403: Permission denied — requires the "remove" permission on containers, images, volumes AND networks for the target environment resp-500: Failed to prune the system (Docker error); the message is returned in "details"
- Source: `src/routes/api/prune/all/+server.ts`

### `POST` `/prune/containers`
POST /api/prune/containers - Remove all stopped containers @openapi summary: Prune (delete) all stopped containers in the target environment query: env:integer Target environment id; scopes both the prune operation and the permission check (defaults to the local environment) (from GET /api/environments) resp-200: Returns { success: true, result } where result is the Docker container-prune report (deleted container ids, space reclaimed) resp-200-example: {"success":true,"result":{"ContainersDeleted":["abc123","def456"],"SpaceReclaimed":5242880}} resp-403: Permission denied — requires the "remove" permission on containers for the target environment resp-500: Failed to prune containers (Docker error)
- Source: `src/routes/api/prune/containers/+server.ts`

### `POST` `/prune/images`
POST /api/prune/images - Remove unused images (streamed job) @openapi summary: Prune unused Docker images, streaming progress as a Server-Sent Events job description: Returns a text/event-stream. On completion a `result` event carries { success, result } on success or { success:false, error } on failure — the operation itself never returns a non-200 HTTP status once the permission check passes. query: dangling:boolean When not "false", prune only dangling images; set "dangling=false" to prune all unused images (defaults to dangling-only) query: env:integer Target environment id; scopes both the prune operation and the permission check (defaults to the local environment) (from GET /api/environments) resp-200: Server-Sent Events stream; the final `result` event contains { success, result } or { success:false, error } resp-403: Permission denied — requires the "remove" permission on images for the target environment
- Source: `src/routes/api/prune/images/+server.ts`

### `POST` `/prune/networks`
POST /api/prune/networks - Remove all unused networks @openapi summary: Prune (delete) all unused Docker networks in the target environment query: env:integer Target environment id; scopes both the prune operation and the permission check (defaults to the local environment) (from GET /api/environments) resp-200: Returns { success: true, result } where result is the Docker network-prune report (deleted network names) resp-200-example: {"success":true,"result":{"NetworksDeleted":["bridge-old","test-net"]}} resp-403: Permission denied — requires the "remove" permission on networks for the target environment resp-500: Failed to prune networks (Docker error)
- Source: `src/routes/api/prune/networks/+server.ts`

### `POST` `/prune/volumes`
POST /api/prune/volumes - Remove all unused volumes @openapi summary: Prune (delete) all unused Docker volumes in the target environment query: env:integer Target environment id; scopes both the prune operation and the permission check (defaults to the local environment) (from GET /api/environments) resp-200: Returns { success: true, result } where result is the Docker volume-prune report (deleted volume names, space reclaimed) resp-200-example: {"success":true,"result":{"VolumesDeleted":["orphan-data"],"SpaceReclaimed":20971520}} resp-403: Permission denied — requires the "remove" permission on volumes for the target environment resp-500: Failed to prune volumes (Docker error)
- Source: `src/routes/api/prune/volumes/+server.ts`

## registries

### `GET, POST` `/registries`
@openapi summary: List all configured container registries with passwords stripped (only a hasCredentials flag) resp-200: array<{id:integer!, name:string!, url:string!, isDefault:boolean, hasCredentials:boolean!}> resp-200-example: [{"id":1,"name":"Docker Hub","url":"https://docker.io","isDefault":true,"hasCredentials":false}] resp-403: Caller lacks the registries:view permission resp-500: Failed to read registries
- Source: `src/routes/api/registries/+server.ts`

### `DELETE, GET, PUT` `/registries/[id]`
- Source: `src/routes/api/registries/[id]/+server.ts`

### `POST` `/registries/[id]/default`
@openapi summary: Mark a registry as the default registry path: id:integer! Registry ID (from GET /api/registries) resp-200: {success:boolean!} resp-200-example: {"success":true} resp-400: The id path segment is not a valid integer resp-403: Caller lacks the settings:edit permission resp-404: No registry exists with that ID resp-500: Failed to set the default registry
- Source: `src/routes/api/registries/[id]/default/+server.ts`

### `POST` `/registries/test`
Test registry connectivity and credentials. Accepts either inline credentials (from the modal form) or a registry ID (to test an already-saved registry using stored credentials).
- Source: `src/routes/api/registries/test/+server.ts`

## registry

### `GET` `/registry/catalog`
@openapi summary: List repositories in a registry's V2 catalog (with Harbor project-API fallback), paginated description: Docker Hub is rejected (no catalog API). For 401/403/404 from the upstream registry the same status is proxied back to the caller. query: registry:integer! ID of the configured registry to query (from GET /api/registries) query: last:string Opaque pagination cursor from a previous page's nextLast resp-200: {repositories:array<{name:string!, description:string, star_count:integer, is_official:boolean, is_automated:boolean}>!, pagination:{pageSize:integer!, hasMore:boolean!, nextLast:string}!} resp-200-example: {"repositories":[{"name":"library/nginx","description":"","star_count":0,"is_official":false,"is_automated":false}],"pagination":{"pageSize":100,"hasMore":false,"nextLast":null}} resp-400: Missing registry parameter, or Docker Hub was targeted (catalog listing unsupported) resp-403: Permission denied (requires registries:view) resp-404: Registry not found, or the registry does not implement the V2 catalog API resp-500: Failed to fetch the catalog resp-503: Could not connect to the registry (connection refused, host not found, or a TLS error)
- Source: `src/routes/api/registry/catalog/+server.ts`

### `DELETE` `/registry/image`
- Source: `src/routes/api/registry/image/+server.ts`

### `GET` `/registry/search`
Thrown when the registry refuses catalog listing to a valid token (GitLab/Harbor, #873).
- Local interfaces: `SearchResult`
- Source: `src/routes/api/registry/search/+server.ts`

### `GET` `/registry/tag-info`
- Local interfaces: `TagInfoResult`
- Source: `src/routes/api/registry/tag-info/+server.ts`

### `GET` `/registry/tags`
- Local interfaces: `TagInfo`, `PaginatedTags`
- Source: `src/routes/api/registry/tags/+server.ts`

## roles

### `GET, POST` `/roles`
@openapi summary: List all roles (built-in and custom); available in setup mode or with an enterprise license resp-200: array<{id:integer!, name:string!, description:string, isSystem:boolean!, permissions:{}}> resp-403: Enterprise license required resp-500: Failed to read the roles
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
Manual Schedule Trigger API - Manually run a schedule POST /api/schedules/[type]/[id]/run - Trigger a manual execution Path params:   - type: 'container_update' | 'git_stack_sync' | 'system_cleanup' | 'env_update_check' | 'image_prune' | 'deploy_log_reconcile'   - id: schedule ID
- Source: `src/routes/api/schedules/[type]/[id]/run/+server.ts`

### `POST` `/schedules/[type]/[id]/toggle`
Toggle schedule enabled/disabled POST /api/schedules/:type/:id/toggle
- Source: `src/routes/api/schedules/[type]/[id]/toggle/+server.ts`

### `GET` `/schedules/executions`
Schedule Executions API - List execution history GET /api/schedules/executions - Returns paginated execution history Query params:   - scheduleType: 'container_update' | 'git_stack_sync'   - scheduleId: number   - environmentId: number   - status: 'queued' | 'running' | 'success' | 'warning' | 'failed' | 'skipped'   - triggeredBy: 'cron' | 'webhook' | 'manual'   - fromDate: ISO date string   - toDate: ISO date string   - limit: number (default 50)   - offset: number (default 0)
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

## secret-providers

### `GET, POST` `/secret-providers`
@openapi summary: List configured secret providers (summaries never include the decrypted config) resp-200: array<{id:integer!, name:string!, type:string!}> resp-403: Permission denied (needs secrets:view) resp-500: Failed to fetch secret providers
- Source: `src/routes/api/secret-providers/+server.ts`

### `DELETE, GET, PUT` `/secret-providers/[id]`
- Source: `src/routes/api/secret-providers/[id]/+server.ts`

### `POST` `/secret-providers/[id]/probe`
- Source: `src/routes/api/secret-providers/[id]/probe/+server.ts`

### `POST` `/secret-providers/[id]/test`
- Source: `src/routes/api/secret-providers/[id]/test/+server.ts`

### `POST` `/secret-providers/test`
Test a provider config before it's persisted to the database. @openapi summary: Test an unsaved provider config (before creating the provider) body: {type:string!, config:object!} body-example: {"type":"vault","config":{"host":"https://vault.example.com","mount":"secret","token":"hvs...."}} resp-200: {ok:boolean!, error:string} resp-200-desc: ok=false carries the reason (invalid type, missing config, or a connection error) - still 200 so the form shows it inline resp-400: Invalid request body resp-403: Permission denied (needs secrets:create)
- Source: `src/routes/api/secret-providers/test/+server.ts`

## self-update

### `POST` `/self-update`
- Source: `src/routes/api/self-update/+server.ts`

### `GET` `/self-update/check`
- Source: `src/routes/api/self-update/check/+server.ts`

### `GET` `/self-update/progress`
Fetch from the local Docker directly. Supports TCP and Unix socket.
- Source: `src/routes/api/self-update/progress/+server.ts`

## settings

### `GET, POST` `/settings/general`
- Local interfaces: `GeneralSettings`
- Source: `src/routes/api/settings/general/+server.ts`

### `GET, PUT` `/settings/navigation`
- Source: `src/routes/api/settings/navigation/+server.ts`

### `DELETE, GET, POST` `/settings/scanner`
- Local interfaces: `ScannerSettings`
- Source: `src/routes/api/settings/scanner/+server.ts`

### `DELETE` `/settings/scanner/cache`
@openapi summary: Clear the vulnerability-scanner cache (local volumes/bind-mount dirs plus each remote environment's scanner volume) resp-200: {success:boolean!, removedVolumes:array<string>!, removedDirs:array<string>!, skippedEnvironments:array<string>!} resp-403: Permission denied resp-500: Failed to clear scanner cache
- Source: `src/routes/api/settings/scanner/cache/+server.ts`

### `GET, POST` `/settings/semver`
@openapi summary: Get the global newer-version-tag (semver) detection config resp-200: {enabled:boolean!, maxBump:string!, matchFlavor:boolean!, includePrerelease:boolean!} resp-200-example: {"enabled":true,"maxBump":"minor","matchFlavor":true,"includePrerelease":false}
- Source: `src/routes/api/settings/semver/+server.ts`

### `GET` `/settings/theme`
Public endpoint for theme settings - no authentication required. Used by the login page to apply the app-level theme before user is authenticated.
- Source: `src/routes/api/settings/theme/+server.ts`

## stacks

### `GET, POST` `/stacks`
- Source: `src/routes/api/stacks/+server.ts`

### `DELETE` `/stacks/[name]`
@openapi summary: Remove a stack completely (compose down + delete files + database cleanup) path: name:string! Stack name (from GET /api/stacks) query: env:integer Environment id (from GET /api/environments) query: force:boolean Force removal even if the compose down step fails query: volumes:boolean Also remove named volumes (docker compose down --volumes) query: files:boolean Delete the stack's on-disk files/directory too (default true; pass files=false to keep them on disk) resp-200: {success:boolean!} resp-200-example: {"success":true} resp-400: Compose down failed and force was not set resp-403: Permission denied, or access denied to this environment resp-404: Compose file not found for this stack resp-500: Unexpected error while removing the stack
- Source: `src/routes/api/stacks/[name]/+server.ts`

### `POST` `/stacks/[name]/check-path-change`
- Source: `src/routes/api/stacks/[name]/check-path-change/+server.ts`

### `GET, PUT` `/stacks/[name]/compose`
- Source: `src/routes/api/stacks/[name]/compose/+server.ts`

### `GET` `/stacks/[name]/delete-preview`
- Source: `src/routes/api/stacks/[name]/delete-preview/+server.ts`

### `POST` `/stacks/[name]/deploy`
- Source: `src/routes/api/stacks/[name]/deploy/+server.ts`

### `GET` `/stacks/[name]/deploys`
GET /api/stacks/[name]/deploys?env=X List of deploy runs recorded for this stack. No log text here — the log lives in a file (Task 5), not in this response; fetch it separately via GET .../deploys/{runId}/log. This route does NOT inherit the no-auth model of /api/jobs/{id}: a job id is an unguessable UUID that lives ten minutes in memory, while a schedule execution id is a small sequential integer that persists forever. Every route under .../deploys checks stacks:view for itself. `env` identifies WHICH environment's runs to list, unlike the other two routes under .../deploys (which derive the environment from the loaded run itself via loadOwnedDeployRun). A stack NAME alone is not unique -- the same name can exist in more than one environment -- so a list without a definite environment would either merge runs from unrelated environments into one response, or get evaluated against the caller's globally-merged permission instead of their permission for one specific environment: `auth.can(..., undefined)` checks the OR of every role's grant across all environments, not "does this caller have stacks:view for env X". A caller with stacks:view scoped to exactly one environment could otherwise get runs -- including timestamps, status, error text and details.userId -- from every environment that happens to have a same-named stack. Two `env` shapes both resolve to the LOCAL environment (environmentId === NULL in schedule_executions): the parameter OMITTED entirely, and the literal string "null". This is not a relaxation of the paragraph above -- it is the environment id createRunRecorder() actually writes for a deploy triggered without an explicit envId, which is the case on a single (local-only) environment install: appendEnvParam() in $lib/stores/environment.ts only appends `env` to the request when envId is truthy, so the UI's own "deploy this stack" call for the local environment NEVER sends an `env` param in the first place. Before this NULL shape was recognized here, EVERY recorded run on a single-environment install was unreachable through this endpoint: any non-null `env` value matches zero rows (`env=0` included -- environment ids are never 0), and omitting `env` was a hard 400. There is no legitimate case where "list runs, no env specified" should silently mean "all environments, merged" -- an explicit, distinguishable id (a real integer, or the NULL/local shape) is still required for every request; only what counts as that definite id changed. Anything that is neither a parseable integer nor the omitted/"null" shape remains a hard 400: parsing happens before the permission check, so `can()` and `canAccessEnvironment()` always see a definite id (a number, or `undefined` for the local case -- never an ambiguous "no filter").
- Source: `src/routes/api/stacks/[name]/deploys/+server.ts`

### `DELETE, GET` `/stacks/[name]/deploys/[runId]`
GET /api/stacks/[name]/deploys/[runId] A single deploy run with all its metadata (no log text -- see .../log).
- Source: `src/routes/api/stacks/[name]/deploys/[runId]/+server.ts`

### `GET` `/stacks/[name]/deploys/[runId]/log`
GET /api/stacks/[name]/deploys/[runId]/log The run's protocol text, straight from the file (Task 5) as text/plain. This is the most sensitive of the four operations -- it is the one that can actually carry secrets that survived redaction -- so it MUST NOT come out looking safe just because a file path happened to be unresolvable. Every check below runs BEFORE the file is ever touched: authentication, then stacks:view, then ownership+environment access via loadOwnedDeployRun (the exact same helper GET/DELETE .../deploys/{runId} use, so this route can never drift into trusting a run it shouldn't). Only once all of that has passed does readRunLog() run at all.
- Source: `src/routes/api/stacks/[name]/deploys/[runId]/log/+server.ts`

### `POST` `/stacks/[name]/down`
@openapi summary: Take a stack down (docker compose down — removes containers, keeps files), asynchronously path: name:string! Stack name (from GET /api/stacks) query: env:integer Environment id (from GET /api/environments) body: {removeVolumes:boolean} body-example: {"removeVolumes":false} resp-200: {jobId:string!} resp-200-desc: Fire-and-forget job id — poll GET /api/jobs/{jobId} for the result. Send "Accept: application/json" (without text/event-stream) to instead block and receive the final {success,output|error} synchronously. resp-200-example: {"jobId":"3f9c5b1a-2e4d-4a6f-9b0a-1c7d8e9f0a1b"} resp-403: Permission denied, or access denied to this environment
- Source: `src/routes/api/stacks/[name]/down/+server.ts`

### `GET, PUT` `/stacks/[name]/env`
- Source: `src/routes/api/stacks/[name]/env/+server.ts`

### `GET, PUT` `/stacks/[name]/env/raw`
GET /api/stacks/[name]/env/raw?env=X @openapi summary: Get the raw .env file content as-is (comments and formatting preserved) for a stack path: name:string! Stack name (from GET /api/stacks) query: env:integer Environment ID the stack belongs to (from GET /api/environments) resp-200: {content:string!, noEnvFile:boolean} resp-200-example: {"content":"FOO=bar\n# comment\nBAZ=qux\n"} resp-403: Permission denied (requires stacks:view, or environment access denied on enterprise) resp-500: Failed to get environment file
- Source: `src/routes/api/stacks/[name]/env/raw/+server.ts`

### `POST` `/stacks/[name]/env/validate`
Docker and Compose built-in env vars consumed implicitly at runtime (not via ${} interpolation)
- Local interfaces: `ValidationResult`
- Source: `src/routes/api/stacks/[name]/env/validate/+server.ts`

### `DELETE, GET, POST` `/stacks/[name]/icon`
- Source: `src/routes/api/stacks/[name]/icon/+server.ts`

### `POST` `/stacks/[name]/relocate`
- Source: `src/routes/api/stacks/[name]/relocate/+server.ts`

### `POST` `/stacks/[name]/restart`
@openapi summary: Restart a stack (mode=restart|ordered|recreate); progress and the final result stream over Server-Sent Events path: name:string! Stack name (from GET /api/stacks) query: env:integer Environment ID the stack belongs to (from GET /api/environments) query: mode:string Restart mode — "recreate" recreates containers (new IDs, re-pull), "ordered" does a stop+start honoring depends_on ordering (same IDs), anything else is a plain in-place restart resp-200: Server-Sent-Events job stream with a final result event ({success, output}) resp-403: Permission denied (requires stacks:restart, or environment access denied on enterprise)
- Source: `src/routes/api/stacks/[name]/restart/+server.ts`

### `POST` `/stacks/[name]/start`
@openapi summary: Start a stack (docker compose start/up), asynchronously path: name:string! Stack name (from GET /api/stacks) query: env:integer Environment id (from GET /api/environments) resp-200: {jobId:string!} resp-200-desc: Fire-and-forget job id — poll GET /api/jobs/{jobId} for the result. Send "Accept: application/json" (without text/event-stream) to instead block and receive the final {success,output|error} synchronously. resp-200-example: {"jobId":"3f9c5b1a-2e4d-4a6f-9b0a-1c7d8e9f0a1b"} resp-403: Permission denied, or access denied to this environment
- Source: `src/routes/api/stacks/[name]/start/+server.ts`

### `POST` `/stacks/[name]/stop`
@openapi summary: Stop a stack (docker compose stop), asynchronously path: name:string! Stack name (from GET /api/stacks) query: env:integer Environment id (from GET /api/environments) resp-200: {jobId:string!} resp-200-desc: Fire-and-forget job id — poll GET /api/jobs/{jobId} for the result. Send "Accept: application/json" (without text/event-stream) to instead block and receive the final {success,output|error} synchronously. resp-200-example: {"jobId":"3f9c5b1a-2e4d-4a6f-9b0a-1c7d8e9f0a1b"} resp-403: Permission denied, or access denied to this environment
- Source: `src/routes/api/stacks/[name]/stop/+server.ts`

### `POST` `/stacks/[name]/validate`
- Source: `src/routes/api/stacks/[name]/validate/+server.ts`

### `POST` `/stacks/adopt`
@openapi summary: Adopt previously discovered compose stacks into Dockhand for a given environment description: environmentId from GET /api/environments. body: {stacks:array<{name:string!, composePath:string!}>!, environmentId:integer!} body-example: {"stacks":[{"name":"web","composePath":"/opt/stacks/web/compose.yaml"}],"environmentId":1} resp-200: {adopted:array<string>!, failed:array<{name:string!, error:string!}>!} resp-200-example: {"adopted":["web"],"failed":[]} resp-400: No stacks provided, missing environmentId, or a stack is missing name/composePath resp-403: Permission denied (requires stacks:create) resp-500: Unexpected error while adopting stacks
- Source: `src/routes/api/stacks/adopt/+server.ts`

### `GET` `/stacks/base-path`
GET /api/stacks/base-path @openapi summary: Return the default Dockhand stacks directory ($DATA_DIR/stacks/) where new stacks are stored by default query: env:integer Environment ID used to select the local or environment-scoped stacks root resp-200: {basePath:string!} resp-200-example: {"basePath":"/data/stacks"} Returns the Dockhand stacks root for the requested environment context. Query params: - env: Environment ID (optional) — when set, returns STACKS_DIR for local envs   with STACKS_DIR configured, otherwise $DATA_DIR/stacks (staging / legacy).
- Source: `src/routes/api/stacks/base-path/+server.ts`

### `GET` `/stacks/default-path`
Get the default path for a new stack — used by the UI to show where files will be created. With location set the path is {location}/{envName}/{stackName}/, otherwise Dockhand's default $DATA_DIR/stacks/{envName}/{stackName}/. @openapi summary: Compute the default compose/env file paths for a new stack, either under a custom base location or under Dockhand's default stacks directory query: name:string! Stack name query: env:integer Environment ID (scopes the path under the environment name) (from GET /api/environments) query: location:string Custom base location path resp-200: {stackDir:string!, composePath:string!, envPath:string!, source:string!} resp-200-example: {"stackDir":"/data/stacks/prod/web","composePath":"/data/stacks/prod/web/compose.yaml","envPath":"/data/stacks/prod/web/.env","source":"default"} resp-400: Stack name is required
- Source: `src/routes/api/stacks/default-path/+server.ts`

### `GET` `/stacks/path-hints`
GET /api/stacks/path-hints?name=stackName&env=envId @openapi summary: Return path hints (working directory and config file paths) extracted from a stack's Docker container labels query: name:string! Stack name (from GET /api/stacks) query: env:integer Environment ID the stack belongs to (from GET /api/environments) resp-200: {stackName:string!, workingDir:string, configFiles:array<string>} resp-200-example: {"stackName":"web","workingDir":"/opt/stacks/web","configFiles":["/opt/stacks/web/compose.yaml"]} resp-400: Stack name is required resp-401: Unauthorized resp-500: Failed to get path hints
- Source: `src/routes/api/stacks/path-hints/+server.ts`

### `POST` `/stacks/scan`
@openapi summary: Scan a given filesystem path (or all configured external paths when none is given) for compose stacks, flagging which discovered stacks are already running body: {path:string} body-example: {"path":"/opt/stacks"} resp-200: {discovered:array<{name:string!}>!, adopted:array<string>!, skipped:array<string>!, errors:array<{path:string!, error:string!}>!} resp-200-example: {"discovered":[{"name":"web"}],"adopted":[],"skipped":[],"errors":[]} resp-403: Permission denied (requires stacks:create) resp-500: Unexpected error while scanning
- Source: `src/routes/api/stacks/scan/+server.ts`

### `GET` `/stacks/sources`
@openapi summary: List stack source records (their stored compose/env paths and source type, plus an env-var count) query: env:integer Filter to a single environment id resp-403: Permission denied (needs stacks:view) resp-500: Failed to list stack sources
- Source: `src/routes/api/stacks/sources/+server.ts`

### `POST` `/stacks/validate-path`
@openapi summary: Validate a candidate external stack path (exists, is a directory, no overlap with already-configured paths); validation failures are returned as 200 with valid=false body: {path:string!} body-example: {"path":"/opt/external-stacks"} resp-200: {valid:boolean!, error:string} resp-200-example: {"valid":false,"error":"Path does not exist"} resp-403: Permission denied (requires settings:edit)
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
GET /api/system/files/content Read file content from Dockhand's local filesystem @openapi summary: Read a text file from Dockhand's local filesystem (max 10MB, protected paths denied) query: path:string! Absolute path of the file to read resp-200: {path:string!, content:string!, size:integer!, mtime:string!} resp-200-example: {"path":"/docker/stacks/myapp/compose.yaml","content":"services:\n  app:\n    image: nginx","size":42,"mtime":"2026-07-01T10:00:00.000Z"} resp-400: Path is missing, points to a directory, or the file exceeds 10MB resp-403: Permission denied, or the path is protected resp-404: File not found resp-500: Failed to read file
- Source: `src/routes/api/system/files/content/+server.ts`

## templates

### `GET` `/templates`
- Local interfaces: `TemplateItem`
- Source: `src/routes/api/templates/+server.ts`

### `POST` `/templates/compose`
- Source: `src/routes/api/templates/compose/+server.ts`

### `DELETE, GET, POST, PUT` `/templates/sources`
GET /api/templates/sources - List configured template sources @openapi summary: List all configured template sources (built-in and custom) resp-200: array<{id:integer!, name:string!, url:string!, enabled:boolean!}> resp-200-example: [{"id":1,"name":"LinuxServer.io","url":"https://fleet.linuxserver.io/api/v1/images","enabled":true}] resp-403: Permission denied
- Source: `src/routes/api/templates/sources/+server.ts`

## users

### `GET, POST` `/users`
- Source: `src/routes/api/users/+server.ts`

### `DELETE, GET, PUT` `/users/[id]`
- Source: `src/routes/api/users/[id]/+server.ts`

### `DELETE, POST` `/users/[id]/mfa`
@openapi summary: Set up or verify MFA for a user (action=setup regenerates a secret; action=verify confirms a code) path: id:integer The user id body: {action:string!, token:string} resp-400: Missing user id, missing/invalid MFA token, or an unknown action resp-403: Permission denied resp-404: User not found resp-409: MFA is already enabled (disable it before setting up again) resp-500: Failed to set up MFA
- Source: `src/routes/api/users/[id]/mfa/+server.ts`

### `DELETE, GET, POST` `/users/[id]/roles`
- Source: `src/routes/api/users/[id]/roles/+server.ts`

## volumes

### `GET, POST` `/volumes`
@openapi summary: List Docker volumes for an environment; returns an empty array when no environment is specified query: env:integer Environment ID to list volumes for (from GET /api/environments) resp-200: array<{Name:string!, Driver:string!, Mountpoint:string, Scope:string, CreatedAt:string}> resp-200-example: [{"Name":"web_data","Driver":"local","Mountpoint":"/var/lib/docker/volumes/web_data/_data","Scope":"local","CreatedAt":"2026-06-01T10:00:00Z"}] resp-403: Permission denied (requires volumes:view, or environment access denied on enterprise) resp-404: Environment not found resp-500: Failed to list volumes
- Source: `src/routes/api/volumes/+server.ts`

### `DELETE, GET` `/volumes/[name]`
@openapi summary: Inspect a single Docker volume by name (the name is validated as a Docker identifier) path: name:string! Docker volume name (from GET /api/volumes) query: env:integer Environment ID the volume belongs to (from GET /api/environments) resp-200: {Name:string!, Driver:string!, Mountpoint:string!, Scope:string, Labels:{}, Options:{}, CreatedAt:string} resp-200-example: {"Name":"web_data","Driver":"local","Mountpoint":"/var/lib/docker/volumes/web_data/_data","Scope":"local","Labels":{},"Options":{},"CreatedAt":"2026-06-01T10:00:00Z"} resp-403: Permission denied (requires volumes:inspect, or environment access denied on enterprise)
- Source: `src/routes/api/volumes/[name]/+server.ts`

### `GET` `/volumes/[name]/browse`
@openapi summary: Browse a directory inside a Docker volume via a cached helper container; the volume is mounted read-only when in use by other containers path: name:string! Docker volume name (from GET /api/volumes) query: env:integer Environment ID the volume belongs to (from GET /api/environments) query: path:string Directory path inside the volume to list (defaults to "/") resp-200: {path:string!, entries:array<{name:string!, type:string!, size:integer!, permissions:string!, owner:string!, group:string!, modified:string!}>!, usage:array<{containerId:string!, containerName:string!, state:string!}>!, isInUse:boolean!, helperId:string!} resp-200-example: {"path":"/","entries":[{"name":"data","type":"directory","size":4096,"permissions":"drwxr-xr-x","owner":"root","group":"root","modified":"2026-06-01 10:00"}],"usage":[],"isInUse":false,"helperId":"abc123"} resp-403: Permission denied (requires volumes:inspect) or permission denied accessing the path resp-404: Directory not found resp-500: Failed to browse volume
- Source: `src/routes/api/volumes/[name]/browse/+server.ts`

### `GET` `/volumes/[name]/browse/content`
@openapi summary: Read the content of a single file inside a Docker volume (files larger than 1MB are rejected) path: name:string! Docker volume name (from GET /api/volumes) query: path:string! File path inside the volume to read query: env:integer Environment ID the volume belongs to (from GET /api/environments) resp-200: {content:string!, path:string!} resp-200-example: {"content":"hello world\n","path":"/data/readme.txt"} resp-400: Path is required, or the path points to a directory resp-403: Permission denied (requires volumes:inspect) or permission denied reading the file resp-404: File not found resp-413: File is too large to view (max 1MB) resp-500: Failed to read file
- Source: `src/routes/api/volumes/[name]/browse/content/+server.ts`

### `POST` `/volumes/[name]/browse/release`
Release the cached volume helper container when done browsing (called when the volume browser modal is closed). @openapi summary: Release the cached helper container used to browse a Docker volume path: name:string! Docker volume name (from GET /api/volumes) query: env:integer Environment ID the volume belongs to (from GET /api/environments) resp-200: {success:boolean!} resp-200-example: {"success":true} resp-403: Permission denied (requires volumes:inspect) resp-500: Failed to release volume helper
- Source: `src/routes/api/volumes/[name]/browse/release/+server.ts`

### `POST` `/volumes/[name]/clone`
- Source: `src/routes/api/volumes/[name]/clone/+server.ts`

### `GET` `/volumes/[name]/export`
- Source: `src/routes/api/volumes/[name]/export/+server.ts`

### `GET` `/volumes/[name]/inspect`
@openapi summary: Inspect a Docker volume by name, returning the raw Docker volume inspect object path: name:string! Docker volume name (from GET /api/volumes) query: env:integer Environment ID the volume belongs to (from GET /api/environments) resp-200: {Name:string!, Driver:string!, Mountpoint:string!, Scope:string, Labels:{}, Options:{}, CreatedAt:string} resp-200-example: {"Name":"web_data","Driver":"local","Mountpoint":"/var/lib/docker/volumes/web_data/_data","Scope":"local","Labels":{},"Options":{},"CreatedAt":"2026-06-01T10:00:00Z"} resp-403: Permission denied (requires volumes:inspect) resp-500: Failed to inspect volume
- Source: `src/routes/api/volumes/[name]/inspect/+server.ts`

## vulnerabilities

### `GET` `/vulnerabilities`
A page of aggregated vulnerability findings for an environment, filtered and sorted server-side. Query: limit, offset, q, severity, image, container, stack, sort, dir. Returns { findings, total } where `total` is the filtered count (for the "X-Y of N" counter and infinite scroll). @openapi summary: A filtered, sorted page of aggregated vulnerability findings for an environment description: Accepts limit, offset, q, severity, image, container, stack, sort and dir query params (parsed centrally). Returns an empty page when no environment resolves. resp-200: {findings:array<object>!, total:integer!} resp-200-desc: A page of findings plus the filtered total count; a permission failure returns the status from the access check resp-200-example: {"findings":[{"cve":"CVE-2024-0001","severity":"high","package":"openssl","imageName":"nginx:latest"}],"total":1}
- Source: `src/routes/api/vulnerabilities/+server.ts`

### `GET` `/vulnerabilities/count`
Vulnerability dashboard metadata for an environment: the total finding count, the severity summary, and the distinct filter-dropdown values (image / container / stack) across the full set. Lets the header badge and the filter dropdowns stay complete without the page loading the full findings array.
- Source: `src/routes/api/vulnerabilities/count/+server.ts`

### `GET` `/vulnerabilities/export`
- Source: `src/routes/api/vulnerabilities/export/+server.ts`

### `POST` `/vulnerabilities/scan-all`
Scan every image in the environment for vulnerabilities. Tagged images scan by tag; untagged but digest-pinned images (e.g. renovate `@sha256:` pins) scan by their repo digest so they aren't silently skipped (#1286). Reuses the per-image scan flow, sequentially, reporting N/total progress. A single image failing does not abort the batch. @openapi summary: Scan every image in an environment for vulnerabilities, streaming per-image progress as Server-Sent Events query: env:integer ID of the environment whose images to scan (from GET /api/environments) resp-200: A Server-Sent Events stream of progress and per-image results, ending with a summary "result" event resp-403: Permission denied, or (enterprise) no access to this environment
- Source: `src/routes/api/vulnerabilities/scan-all/+server.ts`
