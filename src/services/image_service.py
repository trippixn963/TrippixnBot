"""
TrippixnBot - Image Search Service
==================================

Image search using DuckDuckGo (free, no API key needed).

Author: حَـــــنَّـــــا
"""

import aiohttp
import re
import json
from dataclasses import dataclass
from typing import Optional

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
            "off": "-2",
            "medium": "-1",
            "high": "1",
        }
        safe_param = safe_map.get(safe_search, "-1")

        try:
            # First, get the vqd token from DuckDuckGo
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }

            async with aiohttp.ClientSession() as session:
                # Get vqd token
                token_url = f"https://duckduckgo.com/?q={query}&iax=images&ia=images"
                async with session.get(token_url, headers=headers) as resp:
                    if resp.status != 200:
                        return ImageSearchResult(
                            success=False,
                            query=query,
                            images=[],
                            total_results=0,
                            error=f"Failed to get search token: {resp.status}"
                        )

                    html = await resp.text()

                    # Extract vqd token
                    vqd_match = re.search(r'vqd=(["\'])([^"\']+)\1', html)
                    if not vqd_match:
                        vqd_match = re.search(r'vqd=(\d+-\d+(?:-\d+)?)', html)

                    if not vqd_match:
                        return ImageSearchResult(
                            success=False,
                            query=query,
                            images=[],
                            total_results=0,
                            error="Could not extract search token"
                        )

                    vqd = vqd_match.group(2) if vqd_match.lastindex == 2 else vqd_match.group(1)

                # Now search for images
                search_url = "https://duckduckgo.com/i.js"
                params = {
                    "l": "us-en",
                    "o": "json",
                    "q": query,
                    "vqd": vqd,
                    "f": ",,,,,",
                    "p": safe_param,
                }

                async with session.get(search_url, params=params, headers=headers) as resp:
                    if resp.status != 200:
                        return ImageSearchResult(
                            success=False,
                            query=query,
                            images=[],
                            total_results=0,
                            error=f"Image search failed: {resp.status}"
                        )

                    data = await resp.json()

            # Parse results
            images = []
            results = data.get("results", [])

            for item in results[:num_results]:
                images.append(ImageResult(
                    url=item.get("image", ""),
                    title=item.get("title", "No title"),
                    source_url=item.get("url", ""),
                    width=item.get("width", 0),
                    height=item.get("height", 0),
                ))

            log.tree("Image Search Complete", [
                ("Results", len(images)),
            ], emoji="✅")

            return ImageSearchResult(
                success=True,
                query=query,
                images=images,
                total_results=len(images),
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
