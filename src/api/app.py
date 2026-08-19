"""
FastAPI Application Factory and Core Configuration.
Document Intelligence Pipeline - Milestone 1
"""

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routes import router as api_router
from src.config import Settings, get_settings

logger = logging.getLogger("document_intelligence.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Handles startup initialization and graceful shutdown.
    """
    settings: Settings = get_settings()
    logger.info("Initializing Document Intelligence API...")
    logger.info("Environment Mock Mode: %s", settings.is_mock_azure)

    # Ensure upload and data directories exist
    settings.ensure_directories()
    logger.info("Storage directory verified: %s", settings.UPLOAD_DIR.resolve())

    yield

    logger.info("Shutting down Document Intelligence API...")


def create_app(settings: Settings | None = None) -> FastAPI:
    """
    FastAPI Application Factory.
    """
    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "End-to-End Document Intelligence Pipeline for automated invoice "
            "and receipt ingestion, extraction, normalization, and auditing."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Configure CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -------------------------------------------------------------------------
    # Exception Handlers
    # -------------------------------------------------------------------------
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail,
                "status_code": exc.status_code,
                "error_type": "HTTPException",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": exc.errors(),
                "status_code": status.HTTP_422_UNPROCESSABLE_ENTITY,
                "error_type": "ValidationError",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled server exception: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": f"An internal server error occurred: {exc!s}" if settings.DEBUG else "Internal server error.",
                "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "error_type": "InternalServerError",
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    # -------------------------------------------------------------------------
    # Route Registration
    # -------------------------------------------------------------------------
    # Include versioned router (/api/v1) and root-level compatibility router
    app.include_router(api_router, prefix=settings.API_V1_PREFIX, tags=["v1"])
    app.include_router(api_router, tags=["root_compatibility"])

    return app


# Default application instance for ASGI servers (e.g. uvicorn src.api.app:app)
app = create_app()
