"""
TrippixnBot - Image Search Service
==================================

Image search using Google Custom Search API.

Author: حَـــــنَّـــــا
"""

import aiohttp
from dataclasses import dataclass
from typing import Optional

from src.core import config, log


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
    """Service for searching images via Google Custom Search API."""

    SEARCH_URL = "https://www.googleapis.com/customsearch/v1"

    def __init__(self):
        self.api_key = config.GOOGLE_API_KEY
        self.cx = config.GOOGLE_CX
        self._available = bool(self.api_key and self.cx)

        if self._available:
            log.success("Image Search Service initialized")
        else:
            log.warning("Image Search Service disabled - missing GOOGLE_API_KEY or GOOGLE_CX")

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
        Search for images.

        Args:
            query: Search query
            num_results: Number of results to fetch (max 10 per request)
            safe_search: SafeSearch level (off, medium, high)

        Returns:
            ImageSearchResult with list of images
        """
        if not self._available:
            return ImageSearchResult(
                success=False,
                query=query,
                images=[],
                total_results=0,
                error="Image search is not configured. Missing API credentials."
            )

        log.tree("Image Search", [
            ("Query", query),
            ("Results", num_results),
            ("SafeSearch", safe_search),
        ], emoji="🖼️")

        try:
            params = {
                "key": self.api_key,
                "cx": self.cx,
                "q": query,
                "searchType": "image",
                "num": min(num_results, 10),
                "safe": safe_search,
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(self.SEARCH_URL, params=params) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        log.error("Image search failed", [
                            ("Status", resp.status),
                            ("Error", error_text[:200]),
                        ])
                        return ImageSearchResult(
                            success=False,
                            query=query,
                            images=[],
                            total_results=0,
                            error=f"Google API error: {resp.status}"
                        )

                    data = await resp.json()

            # Parse results
            images = []
            items = data.get("items", [])

            for item in items:
                image_info = item.get("image", {})
                images.append(ImageResult(
                    url=item.get("link", ""),
                    title=item.get("title", "No title"),
                    source_url=image_info.get("contextLink", ""),
                    width=image_info.get("width", 0),
                    height=image_info.get("height", 0),
                ))

            total = int(data.get("searchInformation", {}).get("totalResults", 0))

            log.tree("Image Search Complete", [
                ("Results", len(images)),
                ("Total Available", total),
            ], emoji="✅")

            return ImageSearchResult(
                success=True,
                query=query,
                images=images,
                total_results=total,
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


# Global instance
image_service = ImageService()
