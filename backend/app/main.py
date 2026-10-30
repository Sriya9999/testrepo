import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.models  # noqa: F401 - register tables
from app.api import (
    ads,
    agents,
    analytics,
    approvals,
    auth,
    billing,
    brands,
    content,
    dashboard,
    geo,
    integrations,
    seo,
    social,
    workspaces,
)
from app.config import get_settings
from app.db import Base, SessionLocal, engine
from app.errors import register_error_handlers
from app.jobs import sync  # noqa: F401 - register job handlers
from app.seed import seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if settings.auto_create_tables:
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="MarketingOS API", version="1.0.0", lifespan=lifespan,
        description="AI-assisted marketing operating system. All execution that publishes or spends requires approval.",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.web_origin.split(",")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(application)
    for module in (auth, workspaces, brands, content, social, integrations, ads, seo, geo, analytics, approvals, agents,
                   billing, dashboard):
        application.include_router(module.router, prefix=settings.api_prefix)
    application.include_router(brands.public_router)

    @application.get("/health", tags=["ops"])
    def health():
        with SessionLocal() as db:
            db.execute(__import__("sqlalchemy").text("SELECT 1"))
        return {"status": "ok"}

    @application.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    return application


app = create_app()
