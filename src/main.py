from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.application_attempts import router as application_attempts_router
from src.api.application_packets import router as application_packets_router
from src.api.applications import router as applications_router
from src.api.ats_assistance import router as ats_assistance_router
from src.api.discovery import router as discovery_router
from src.api.evidence import router as evidence_router
from src.api.follow_ups import router as follow_ups_router
from src.api.jobs import router as jobs_router
from src.api.materials import router as materials_router
from src.api.profiles import router as profile_router
from src.config import get_settings
from src.errors import register_exception_handlers
from src.logging_config import configure_logging

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("jobflow.api")

app = FastAPI(title=settings.app_name)
app.include_router(profile_router)
app.include_router(evidence_router)
app.include_router(applications_router)
app.include_router(application_packets_router)
app.include_router(application_attempts_router)
app.include_router(ats_assistance_router)
app.include_router(follow_ups_router)
app.include_router(discovery_router)
app.include_router(jobs_router)
app.include_router(materials_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in settings.frontend_origins.split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_exception_handlers(app)


@app.middleware("http")
async def request_logging_middleware(request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid4().hex
    request.state.request_id = request_id
    started_at = perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request_failed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
            },
        )
        raise

    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_completed",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((perf_counter() - started_at) * 1000, 2),
        },
    )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
    }
