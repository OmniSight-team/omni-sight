import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.admin import router as admin_router
from app.auth import router as auth_router
from app.cameras import router as cameras_router
from app.deps import RENEWED_TOKEN_HEADER
from app.extraction import mark_interrupted_extractions
from app.logging_conf import configure_logging
from app.nav import router as nav_router
from app.settings import settings
from app.videos import router as videos_router

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
    yield


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
app.include_router(nav_router)
app.include_router(videos_router)


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
