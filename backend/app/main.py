"""FastAPI app entrypoint. Routers (enroll, webhooks, admin) mount in later slices."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.db import engine
from app.pull_errors import new_error_id, unexpected_detail
from app.routers import admin, auth, enroll, public, webhooks

settings = get_settings()
log = logging.getLogger("wearable_hub")

app = FastAPI(title=settings.app_name, version=settings.app_version)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(enroll.router)
app.include_router(public.router)
app.include_router(webhooks.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Safety net: never return a bare 'Internal Server Error' without a log-correlatable ref.

    HTTPException / validation errors keep FastAPI's default handlers (more specific).
    Tracebacks stay in server logs; the body is a safe message + error_id only.
    """
    error_id = new_error_id()
    log.exception(
        "unhandled error_id=%s method=%s path=%s",
        error_id,
        request.method,
        request.url.path,
    )
    return JSONResponse(status_code=500, content={"detail": unexpected_detail(error_id)})


@app.get("/health")
def health() -> dict:
    """Liveness + DB connectivity + which Google config is still missing.

    `google_config` reports booleans (set/unset), never the secret values — handy while
    wiring up the Cloud Console credentials.
    """
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    google_config = {
        "client_id": bool(settings.google_client_id),
        "client_secret": bool(settings.google_client_secret),
        "scopes": bool(settings.google_health_scopes),
        "project_id": bool(settings.gh_project_id),
    }
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "env": settings.environment,
        "db": db_ok,
        "google_config": google_config,
        "google_ready": all(google_config.values()),
    }
