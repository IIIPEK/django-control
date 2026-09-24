# django-control

Django control plane for managed service configuration.

## Managed parameter catalog

Preview an import without changing PostgreSQL:

```powershell
python manage.py sync_managed_catalog `
  --env-file .\no_commit\fastapi-ai-backend.env `
  --environment production `
  --dry-run
```

Apply the catalog and non-secret values:

```powershell
python manage.py sync_managed_catalog `
  --env-file .\no_commit\fastapi-ai-backend.env `
  --environment production
```

Definitions are loaded from versioned JSON manifests in
`control/catalogs/manifests/`, with one parameter manifest per service and a
shared category manifest. Adding or changing a definition requires editing its
JSON manifest and running `sync_managed_catalog`; Django does not need a
restart because the runtime API reads definitions from PostgreSQL. The command
is idempotent. Secret and bootstrap parameters are registered in
the catalog but their values are never copied from the env file. Unknown keys
are reported by name and are not imported.

`sync_fastapi_catalog` remains available as a backward-compatible alias.

Use `--no-update` to create only missing values while preserving existing
values and their active status (including values edited in Admin). Catalog
categories and definitions are still synchronized. It can be combined with
`--dry-run`.

## Read-only configuration API

The endpoint accepts one or more service query parameters:

```text
GET /api/v1/config/production/?service=fastapi&service=voice
Authorization: Bearer <DJANGO_CONFIG_API_KEY>
```

Only active database-sourced, non-secret definitions are returned. Stored
environment values take precedence over catalog defaults. Required parameters
without either value are listed in `missing_required`.

The response uses a stable `ETag`. Send it in `If-None-Match` to receive `304
Not Modified` when the effective configuration has not changed. Only `GET` and
`HEAD` are allowed.

`VLM_MODEL` and `CLASSIFICATION_LLM_MODEL` accept `auto` and `auto-detect` as
ordinary database values. FastAPI resolves either value through `/v1/models`.

## Hashed mail API credentials

Mail agent and administrator keys are managed under **API credentials** in
Django Admin. A key can be entered manually or generated automatically. The
plaintext value is never stored; PostgreSQL contains its SHA-256 digest and a
12-character key ID. Automatically generated keys are displayed once after
saving.

Each credential has one or more capability scopes selected with checkboxes:

```text
mail.api
sql.query
voice.transcribe
diarization.run
```

For agent credentials, the inline mail policy editor accepts one mailbox and
recipient domain per line and exposes permissions as checkboxes. Use `*` as a
recipient domain to allow every domain.

Mail permissions are independent capabilities. `mail.read` permits reading
messages, `mail.mark_read` permits an explicit message status update without
granting `mail.workflow`, and `mail.workflow` permits claim/complete/fail/move
operations.

FastAPI can retrieve active, non-expired credential hashes and policies from:

```text
GET /api/v1/credentials/production/
Authorization: Bearer <DJANGO_CONFIG_API_KEY>
```

The mail-only compatibility endpoint remains available:

```text
GET /api/v1/credentials/mail/production/
Authorization: Bearer <DJANGO_CONFIG_API_KEY>
```

The endpoint is read-only and supports `ETag`/`If-None-Match`. The returned
hashes are used for local verification of incoming bearer keys; plaintext API
keys are never returned.

## Microsoft Teams Graph control

The `teams-graph` service contains managed configuration for a future FastAPI
Teams API/MCP:

```text
TEAMS_GRAPH_TENANT_ID
TEAMS_GRAPH_CLIENT_ID
TEAMS_GRAPH_DEFAULT_SCOPE
TEAMS_GRAPH_TIMEOUT_SECONDS
TEAMS_GRAPH_MAX_RETRIES
TEAMS_GRAPH_ALLOWED_USER_IDS
TEAMS_GRAPH_ALLOWED_USER_PRINCIPALS
TEAMS_GRAPH_ALLOWED_TEAM_IDS
TEAMS_GRAPH_ALLOWED_CHANNEL_IDS
TEAMS_GRAPH_ALLOWED_CHAT_IDS
TEAMS_GRAPH_MAX_DAYS_BACK
TEAMS_GRAPH_MAX_RESULTS
TEAMS_GRAPH_ATTACHMENTS_ENABLED
```

`TEAMS_GRAPH_CLIENT_SECRET` is intentionally absent from the managed catalog
and remains only in the FastAPI environment file. Read the managed values with:

```text
GET /api/v1/config/production/?service=teams-graph
Authorization: Bearer <DJANGO_CONFIG_API_KEY>
```

Migration `0005` creates the `teams-agent` access role with these scopes:

```text
teams.messages.search
teams.messages.read
teams.attachments.read
```

Create a Teams credential under **API credentials**, select the `teams-agent`
access role, and fill the collapsed **Teams Graph policy** section. Resource
lists accept one ID or principal per line; `Maximum days back` is an optional
per-credential restriction. The general credentials endpoint returns the
policy without exposing the plaintext key:

```json
{
  "key_id": "0123456789ab",
  "key_hash": "<sha256>",
  "roles": ["teams-agent"],
  "scopes": [
    "teams.attachments.read",
    "teams.messages.read",
    "teams.messages.search"
  ],
  "policy": {
    "allowed_user_ids": ["user-id"],
    "allowed_user_principals": ["agent@example.com"],
    "allowed_team_ids": ["team-id"],
    "allowed_channel_ids": ["channel-id"],
    "allowed_chat_ids": ["chat-id"],
    "max_days_back": 14
  }
}
```

## Teams Transcript Worker control

The separate `teams-transcript-worker` service contains non-secret managed
configuration for the Teams transcript archiver:

```text
TEAMS_TRANSCRIPT_TENANT_ID
TEAMS_TRANSCRIPT_CLIENT_ID
TEAMS_TRANSCRIPT_GRAPH_SCOPE
TEAMS_TRANSCRIPT_FOCUS_USER_ID
TEAMS_TRANSCRIPT_PRIORITY_CONTACT_USER_ID
TEAMS_TRANSCRIPT_PRIORITY_CONTACT_DISPLAY_NAME
TEAMS_TRANSCRIPT_SALES_GROUP_ID
TEAMS_TRANSCRIPT_SHAREPOINT_SITE_ID
TEAMS_TRANSCRIPT_SHAREPOINT_LIBRARY_NAME
TEAMS_TRANSCRIPT_SOURCE_ROOT_PATH
TEAMS_TRANSCRIPT_SALES_PATH
TEAMS_TRANSCRIPT_PRIORITY_CONTACT_PATH
TEAMS_TRANSCRIPT_GROUP_CALLS_PATH
TEAMS_TRANSCRIPT_NOTIFICATION_URL
TEAMS_TRANSCRIPT_TIMEZONE
TEAMS_TRANSCRIPT_GRAPH_TIMEOUT_SECONDS
TEAMS_TRANSCRIPT_GRAPH_MAX_RETRIES
TEAMS_TRANSCRIPT_RECONCILIATION_INTERVAL_SECONDS
TEAMS_TRANSCRIPT_LOOKBACK_HOURS
TEAMS_TRANSCRIPT_SALES_CACHE_TTL_SECONDS
TEAMS_TRANSCRIPT_SUBSCRIPTION_RENEW_BEFORE_MINUTES
TEAMS_TRANSCRIPT_FINALIZATION_RETRY_SECONDS
TEAMS_TRANSCRIPT_PROCESSING_STALE_SECONDS
TEAMS_TRANSCRIPT_SUMMARY_ENABLED
TEAMS_TRANSCRIPT_SUMMARY_ENABLE_THINKING
TEAMS_TRANSCRIPT_SUMMARY_LLM_URL
TEAMS_TRANSCRIPT_SUMMARY_LLM_MODEL
TEAMS_TRANSCRIPT_SUMMARY_TIMEOUT_SECONDS
TEAMS_TRANSCRIPT_SUMMARY_MAX_TOKENS
TEAMS_TRANSCRIPT_SUMMARY_MAX_INPUT_CHARS
TEAMS_TRANSCRIPT_REPORTS_ROOT_PATH
```

Summary settings are managed values. When the model is `auto`, the worker must
resolve the available model through the LLM server's `/v1/models` endpoint;
Django only stores and returns the string. The LLM URL must be reachable from
the worker host. Enabling summaries requires worker-side support.

The worker is a managed-config service, not an access role. Its Graph client
secret, notification `clientState`, state database URL, and Django Control API
key remain only in the worker environment file. They are intentionally absent
from this catalog.

Import the non-secret values and defaults with:

```powershell
python manage.py sync_managed_catalog `
  --env-file "C:\iv\Python\django-control\no_commit\teams-transcript-worker-managed.env" `
  --environment production `
  --dry-run
```

To preserve worker values already edited in Admin, add `--no-update` to both
the dry run and the applying command. After reviewing the dry run, repeat
without `--dry-run`. The worker reads the
effective values from:

```text
GET /api/v1/config/production/?service=teams-transcript-worker
Authorization: Bearer <DJANGO_CONFIG_API_KEY>
```

## Access roles and SQL profiles

API scopes are normalized database records and are assigned through reusable
access roles. The credentials endpoint remains schema version 2 for FastAPI
compatibility and now also returns role codes and SQL profile codes. Standard
roles created by the migrations include `mail-agent`, `sql-consumer`,
`sql-maintainer`, `voice-client`, `diarization-client`, and `teams-agent`.

The legacy `sql.query` scope remains on SQL roles during the FastAPI migration.
The granular SQL scopes are:

```text
sql.catalog.read
sql.query.execute
sql.query.upload
```

SQL access is deny-by-default. A credential must have an execution scope and a
SQL access profile; that profile must have an explicit grant for the requested
query.

## Versioned SQL catalog

SQL queries have stable `Q-00` or `Q-00-00` keys, categories, descriptions,
immutable revisions, environment-specific publications, access-profile grants,
and ordered multi-step relationships. Editing a query revision does not change
production until that revision is explicitly published.

FastAPI can retrieve enabled publications from:

```text
GET /api/v1/sql-catalog/production/
Authorization: Bearer <DJANGO_CONFIG_API_KEY>
```

The response is read-only and supports `ETag`/`If-None-Match`. SQL text is sent
only to the trusted FastAPI control-plane client, not to ordinary SQL API
callers.

Preview importing the existing FastAPI registry and SQL files:

```powershell
python manage.py sync_sql_catalog `
  --registry-file C:\iv\Python\FastAPI_AI_backend\sql\registry.json `
  --environment production `
  --dry-run
```

Apply the import after reviewing the preview:

```powershell
python manage.py sync_sql_catalog `
  --registry-file C:\iv\Python\FastAPI_AI_backend\sql\registry.json `
  --environment production
```

The command is idempotent. Changed SQL creates a new immutable revision;
unchanged SQL reuses its existing checksum. Section profiles and grants are
created without assigning those profiles to credentials.

Run tests without requiring PostgreSQL `CREATEDB` permission:

```powershell
python manage.py test control --settings=config.test_settings
```
