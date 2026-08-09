from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND_DIST, ensure_dirs
from .db import init_db
from .logging_config import get_logger, setup_logging
from .middleware import RequestLogMiddleware
from .routers import classify, compose, entries, materials

SERVICE_NAME = "star-invoice-helper"
SERVICE_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    log = get_logger("startup")
    ensure_dirs()
    init_db()
    log.info("service=%s version=%s ready", SERVICE_NAME, SERVICE_VERSION)
    yield
    get_logger("startup").info("service shutting down")


app = FastAPI(title="Star Invoice Helper", version=SERVICE_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLogMiddleware)

app.include_router(entries.router)
app.include_router(materials.router)
app.include_router(compose.router)
app.include_router(classify.router)


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    get_logger("error").exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


def _mount_frontend() -> None:
    if not FRONTEND_DIST.exists():
        get_logger("startup").info("frontend dist not found, API-only mode")
        return

    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        # Never claim to handle API here — let FastAPI 404 naturally for unknown API paths
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail=f"API route not found: /{full_path}")
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")

    get_logger("startup").info("frontend dist mounted from %s", FRONTEND_DIST)


_mount_frontend()
