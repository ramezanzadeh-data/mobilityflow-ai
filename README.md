# MobilityFlow AI

Multi-tenant SaaS platform for Swiss workforce relocation and immigration
case management: AI-assisted document processing, risk scoring, workflow
automation, and a REST API - all scoped per tenant (company).

## Database

Runs on PostgreSQL (SQLite is not supported). Configure via either:

- `DATABASE_URL` (e.g. `postgresql://user:password@host:5432/dbname`), or
- the individual `PGHOST` / `PGPORT` / `PGDATABASE` / `PGUSER` / `PGPASSWORD` variables

See `.env.example` for the full list of environment variables, including
the first-run bootstrap admin account (`DEFAULT_ADMIN_USERNAME` /
`DEFAULT_ADMIN_PASSWORD` / `DEFAULT_ADMIN_COMPANY`).

### Quick start with Docker

```
docker compose up
```

This starts PostgreSQL, Redis, a Celery worker, the Streamlit app (port
8501), and the REST API (port 8000).

## Background workers

OCR, AI generation (recommendations, document classification), email/
checklist/letter generation, PDF export, and webhook notifications all
run as Celery background jobs (broker/result backend: Redis) instead of
blocking a request.

Run a worker locally (outside Docker):

```
celery -A workers.celery_app worker --loglevel=info
```

API endpoints that enqueue a job return `202 Accepted` with a `task_id`
and a `status_url`. Poll `GET /api/v1/jobs/{task_id}` for the state
(`PENDING` / `STARTED` / `SUCCESS` / `FAILURE`) and result.

### Managing users

Use `scripts/manage_users.py` - this is the only supported way to create
or reset user accounts:

```
python -m scripts.manage_users create-admin --username admin --password admin --company "Default Company"
python -m scripts.manage_users create-user --username jsmith --password s3cret --role STAFF --company "Acme AG"
python -m scripts.manage_users reset-password --username admin --password new-password
python -m scripts.manage_users list-users
```

## Security & multi-tenancy

- **Tenant isolation is enforced at the database level**, not just in application code: every tenant-scoped table has PostgreSQL Row-Level Security (`FORCE ROW LEVEL SECURITY`) tied to the request's tenant. A route-level bug that forgets to check tenant ownership still can't read or write another tenant's data.
- **Auth**: JWT access tokens (short-lived) + rotating refresh tokens (`POST /auth/refresh`), per-device session listing/revocation (`GET /auth/sessions`, `DELETE /auth/sessions/{id}`, `POST /auth/logout-all`), and optional TOTP-based MFA (`POST /auth/mfa/setup` / `/mfa/enable` / `/mfa/disable`).
- **RBAC**: a real permission matrix (`ADMIN` / `MANAGER` / `STAFF` / `VIEWER`) backed by `permissions` + `role_permissions` tables - see `db.database._ROLE_PERMISSIONS`. Enforced via the `require_permission(...)` FastAPI dependency.

## Object storage

Uploaded documents and generated PDF reports are stored in S3 or MinIO (`core/storage/object_storage.py`) - never on the app's own disk. Configure `S3_ENDPOINT_URL` to point at MinIO (or leave unset for real AWS S3).
