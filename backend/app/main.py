"""FastAPI app entrypoint. Routers (enroll, webhooks, admin) mount in later slices."""

from fastapi import FastAPI
from sqlalchemy import text

from app.config import get_settings
from app.db import engine
from app.routers import admin, enroll, webhooks

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.include_router(admin.router)
app.include_router(enroll.router)
app.include_router(webhooks.router)


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
        "env": settings.environment,
        "db": db_ok,
        "google_config": google_config,
        "google_ready": all(google_config.values()),
    }
