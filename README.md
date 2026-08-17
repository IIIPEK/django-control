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
