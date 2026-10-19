from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    auth, cron, dashboard, domains, hosting, integrations, notifications, public, registrars, settings, system,
)
from app.api.errors import install_error_handlers
from app.config import get_settings
from app.logging_setup import configure_logging

API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    config = get_settings()
    configure_logging()
    app = FastAPI(
        title="Domain & Hosting Monitor API",
        version="1.0.0",
        docs_url=None if config.is_production else f"{API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=None if config.is_production else f"{API_PREFIX}/openapi.json",
    )
    install_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.url.path.startswith(API_PREFIX):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    for module in (auth, cron, domains, hosting, registrars, dashboard, notifications, settings, integrations, public, system):
        app.include_router(module.router, prefix=API_PREFIX)
    return app


app = create_app()
