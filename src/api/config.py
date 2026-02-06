"""
TrippixnBot - API Configuration
===============================

Configuration for the FastAPI server.

Author: حَـــــنَّـــــا
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class APIConfig:
    """API server configuration."""

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8085

    # Rate limiting
    rate_limit_requests: int = 60
    rate_limit_window: int = 60

    # GitHub settings
    github_username: str = ""
    github_token: str = ""

    # API key for protected endpoints
    commits_api_key: str = ""

    # CORS
    cors_origins: list = None

    def __post_init__(self):
        if self.cors_origins is None:
            self.cors_origins = ["*"]


_config: Optional[APIConfig] = None


def get_api_config() -> APIConfig:
    """Get or create API configuration from environment."""
    global _config
    if _config is None:
        _config = APIConfig(
            host=os.getenv("TRIPPIXN_API_HOST", "0.0.0.0"),
            port=int(os.getenv("TRIPPIXN_API_PORT", "8085")),
            rate_limit_requests=int(os.getenv("API_RATE_LIMIT", "60")),
            rate_limit_window=int(os.getenv("API_RATE_WINDOW", "60")),
            github_username=os.getenv("GITHUB_USERNAME", ""),
            github_token=os.getenv("GITHUB_TOKEN", ""),
            commits_api_key=os.getenv("COMMITS_API_KEY", ""),
        )
    return _config


__all__ = ["APIConfig", "get_api_config"]
