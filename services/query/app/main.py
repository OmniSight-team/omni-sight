import logging
import time
from contextlib import asynccontextmanager, closing

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from omnisight_common.clip_vectors import ensure_clip_collection
from omnisight_common.frame_vectors import ensure_frame_collection, qdrant_client

from app.admin import router as admin_router
from app.auth import router as auth_router
from app.cameras import router as cameras_router
from app.dashboard import router as dashboard_router
from app.capture_resume import start_background as start_capture_resume
from app.datasets import router as datasets_router
from app.embeddings import router as embeddings_router
from app.deps import RENEWED_TOKEN_HEADER
from app.extraction import mark_interrupted_extractions
from app.logging_conf import configure_logging
from app.metrics import router as metrics_router
from app.nav import router as nav_router
from app.search import router as search_router
from app.settings import settings
from app.videos import router as videos_router
from app.windows import router as windows_router

configure_logging()
logger = logging.getLogger("app.request")



@asynccontextmanager
async def lifespan(_app: FastAPI):
    # A video still `extracting` at startup lost its background task with the
    # previous process; without this it would stay in that state forever.
    try:
        mark_interrupted_extractions()
    except Exception as exc:  # noqa: BLE001 - the app should still start
        logger.error("startup extraction sweep failed", extra={"extra_fields": {"error": str(exc)}})
    # OMNI-703, 710: both collections are created if missing, never recreated. Logged, not fatal:
    # everything but search still works without Qdrant.
    try:
        with closing(qdrant_client(settings)) as client:
            if ensure_frame_collection(client, settings.frame_collection):
                logger.info("created the frame vector collection", extra={"extra_fields": {"name": settings.frame_collection}})
            if ensure_clip_collection(client, settings.clip_collection):
                logger.info("created the clip vector collection", extra={"extra_fields": {"name": settings.clip_collection}})
    except Exception as exc:  # noqa: BLE001 - the app should still start
        logger.error("vector collection check failed", extra={"extra_fields": {"error": str(exc)}})
    # OMNI-504: cameras that should be captured are started again whenever
    # ingestion has no worker for them, after a restart of either service.
    resumer = start_capture_resume(settings.capture_resume_interval_s)
    yield
    if resumer is not None:
        resumer.stop()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[RENEWED_TOKEN_HEADER],
)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(cameras_router)
app.include_router(dashboard_router)
app.include_router(datasets_router)
app.include_router(embeddings_router)
app.include_router(metrics_router)
app.include_router(nav_router)
app.include_router(search_router)
app.include_router(videos_router)
app.include_router(windows_router)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "request",
        extra={
            "extra_fields": {
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            }
        },
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled_exception",
        extra={"extra_fields": {"path": request.url.path, "error": str(exc)}},
    )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
