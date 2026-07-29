# Must run before any application module is imported: db.database,
# auth.jwt and auth.encryption all read configuration at import time.
# Without it, a uvicorn process started directly on a developer machine
# (rather than through Docker Compose) silently falls back to
# db.database._build_pool()'s localhost defaults - see
# bootstrap/environment.py.
from bootstrap import load_environment

load_environment()

from fastapi import APIRouter, FastAPI  # noqa: E402  (deliberate - see above)
from fastapi.openapi.utils import get_openapi  # noqa: E402

from apps.api.middleware.security import SecurityHeadersMiddleware  # noqa: E402
from apps.api.routes import (  # noqa: E402
    auth,
    cases,
    webhooks,
    documents,
    reports,
    tasks,
    users,
    jobs,
    communications,
)


TAGS_METADATA = [
    {
        "name": "auth",
        "description": "Login and obtain JWT access and refresh tokens.",
    },
    {
        "name": "cases",
        "description": "Read and manage relocation cases.",
    },
    {
        "name": "documents",
        "description": "Manage case documents and OCR processing.",
    },
    {
        "name": "tasks",
        "description": "Manage workflow tasks.",
    },
    {
        "name": "reports",
        "description": "Generate PDF and Excel reports.",
    },
    {
        "name": "communications",
        "description": "Generate emails, checklists and letters.",
    },
    {
        "name": "jobs",
        "description": "Monitor background jobs.",
    },
    {
        "name": "users",
        "description": "Manage users and profiles.",
    },
    {
        "name": "webhooks",
        "description": "Manage webhook integrations.",
    },
]


app = FastAPI(
    title="MobilityFlow AI API",
    description=(
        "REST API for MobilityFlow AI. "
        "Authenticate using POST /api/v1/auth/login "
        "and use Authorization: Bearer <JWT>."
    ),
    version="1.0.0",
    openapi_tags=TAGS_METADATA,
)


# -------------------------------
# Security Headers
# -------------------------------

app.add_middleware(SecurityHeadersMiddleware)


# -------------------------------
# Health Endpoints
# -------------------------------

@app.get(
    "/health",
    tags=["health"],
    summary="Health check",
)
def health_check():
    return {
        "status": "healthy",
        "service": "MobilityFlow AI API",
    }


@app.get(
    "/",
    tags=["health"],
    summary="API information",
)
def root():

    return {
        "service": "MobilityFlow AI API",
        "version": "1.0.0",
        "docs": "/docs",
    }


# -------------------------------
# API v1 Router
# -------------------------------

v1_router = APIRouter(
    prefix="/api/v1",
)


v1_router.include_router(auth.router)
v1_router.include_router(cases.router)
v1_router.include_router(documents.router)
v1_router.include_router(tasks.router)
v1_router.include_router(reports.router)
v1_router.include_router(communications.router)
v1_router.include_router(jobs.router)
v1_router.include_router(users.router)
v1_router.include_router(webhooks.router)


app.include_router(v1_router)


# -------------------------------
# OpenAPI JWT Configuration
# -------------------------------

def custom_openapi():

    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    }

    openapi_schema["security"] = [
        {
            "BearerAuth": []
        }
    ]

    app.openapi_schema = openapi_schema

    return app.openapi_schema


app.openapi = custom_openapi