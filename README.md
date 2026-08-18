# django-control

Django control plane for managed FastAPI configuration.

## FastAPI parameter catalog

Preview an import without changing PostgreSQL:

```powershell
python manage.py sync_fastapi_catalog `
  --env-file .\no_commit\fastapi-ai-backend.env `
  --environment production `
  --dry-run
```

Apply the catalog and non-secret values:

```powershell
python manage.py sync_fastapi_catalog `
  --env-file .\no_commit\fastapi-ai-backend.env `
  --environment production
```

The command is idempotent. Secret and bootstrap parameters are registered in
the catalog but their values are never copied from the env file. Unknown keys
are reported by name and are not imported.

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
