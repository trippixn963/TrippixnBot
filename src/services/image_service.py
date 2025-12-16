"""
TrippixnBot - Image Search Service
==================================

Image search using DuckDuckGo (free, no API key needed).

Author: حَـــــنَّـــــا
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

from duckduckgo_search import DDGS

from src.core import log


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ImageResult:
    """A single image search result."""
    url: str
    title: str
    source_url: str
    width: int
    height: int


@dataclass
class ImageSearchResult:
    """Result of an image search."""
    success: bool
    query: str
    images: list[ImageResult]
    total_results: int
    error: Optional[str] = None


# =============================================================================
# Image Search Service
# =============================================================================

class ImageService:
    """Service for searching images via DuckDuckGo."""

    def __init__(self):
        self._available = True
        log.success("Image Search Service initialized (DuckDuckGo)")

    @property
    def is_available(self) -> bool:
        return self._available

    async def search(
        self,
        query: str,
        num_results: int = 10,
        safe_search: str = "medium"
    ) -> ImageSearchResult:
        """
        Search for images using DuckDuckGo.

        Args:
            query: Search query
            num_results: Number of results to fetch
            safe_search: SafeSearch level (off, medium, high)

        Returns:
            ImageSearchResult with list of images
        """
        log.tree("Image Search", [
            ("Query", query),
            ("Results", num_results),
            ("SafeSearch", safe_search),
        ], emoji="🖼️")

        # Map safe search levels
        safe_map = {
            "off": "off",
            "medium": "moderate",
            "high": "strict",
        }
        safe_param = safe_map.get(safe_search, "moderate")

        try:
            # Run in thread pool since DDGS is sync
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                None,
                self._search_sync,
                query,
                num_results,
                safe_param
            )

            log.tree("Image Search Complete", [
                ("Results", len(results)),
            ], emoji="✅")

            return ImageSearchResult(
                success=True,
                query=query,
                images=results,
                total_results=len(results),
            )

        except Exception as e:
            log.error("Image search error", [
                ("Error", type(e).__name__),
                ("Message", str(e)),
            ])
            return ImageSearchResult(
                success=False,
                query=query,
                images=[],
                total_results=0,
                error=str(e)
            )

    def _search_sync(self, query: str, num_results: int, safe_search: str) -> list[ImageResult]:
        """Synchronous search using DDGS."""
        images = []

        with DDGS() as ddgs:
            results = ddgs.images(
                keywords=query,
                max_results=num_results,
                safesearch=safe_search,
            )

            for item in results:
                images.append(ImageResult(
                    url=item.get("image", ""),
                    title=item.get("title", "No title"),
                    source_url=item.get("url", ""),
                    width=item.get("width", 0),
                    height=item.get("height", 0),
                ))

        return images


# Global instance
image_service = ImageService()
