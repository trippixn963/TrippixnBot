"""
TrippixnBot - FastAPI Application
=================================

Application factory and configuration.

Author: حَـــــنَّـــــا
Server: discord.gg/syria
"""

from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from src.core import log
from src.api.config import get_api_config
from src.api.middleware.rate_limit import RateLimitMiddleware, get_rate_limiter
from src.api.middleware.logging import LoggingMiddleware


# =============================================================================
# Lifespan
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    Handles startup and shutdown events.
    """
    # Startup
    log.debug("API Lifespan Started", [])
    yield
    # Shutdown
    log.debug("API Lifespan Ended", [])


# =============================================================================
# Application Factory
# =============================================================================

def create_app(api_service: Optional[Any] = None) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        api_service: The API service instance with bot reference.

    Returns:
        Configured FastAPI application.
    """
    config = get_api_config()

    # Create app
    app = FastAPI(
        title="TrippixnBot API",
        description="Portfolio stats API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    # Store API service reference
    app.state.api_service = api_service

    # =========================================================================
    # Middleware (order matters - last added = first executed)
    # =========================================================================

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Rate limiting
    app.add_middleware(RateLimitMiddleware, rate_limiter=get_rate_limiter())

    # Request logging
    app.add_middleware(LoggingMiddleware)

    # =========================================================================
    # Exception Handlers
    # =========================================================================

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Handle uncaught exceptions."""
        log.error("Unhandled API Error", [
            ("Path", str(request.url.path)[:50]),
            ("Error", str(exc)[:100]),
        ])

        return JSONResponse(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "Internal server error"},
        )

    # =========================================================================
    # Routers
    # =========================================================================

    from src.api.routers import health, stats, avatar

    app.include_router(health.router)
    app.include_router(stats.router)
    app.include_router(avatar.router)

    return app


# =============================================================================
# Module-level app for uvicorn
# =============================================================================

# This allows running with: uvicorn src.api.app:app
app = create_app()


__all__ = ["create_app", "app"]
