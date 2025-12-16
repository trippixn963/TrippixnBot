"""
TrippixnBot - Image Search Service
==================================

Image search using SearXNG public instances (free, no API key needed).
Aggregates results from Google, Bing, and other search engines.

Author: حَـــــنَّـــــا
"""

import aiohttp
import random
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
# SearXNG Public Instances (with JSON API enabled)
# =============================================================================

SEARXNG_INSTANCES = [
    "https://search.sapti.me",
    "https://searx.tiekoetter.com",
    "https://search.bus-hit.me",
    "https://searx.be",
    "https://search.ononoki.org",
    "https://searx.namejeff.xyz",
    "https://search.rhscz.eu",
    "https://searx.oxf.fr",
]


# =============================================================================
# Image Search Service
# =============================================================================

class ImageService:
    """Service for searching images via SearXNG."""

    def __init__(self):
        self._available = True
        self._instances = SEARXNG_INSTANCES.copy()
        log.success("Image Search Service initialized (SearXNG)")

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
        Search for images using SearXNG.

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

        # Map safe search levels (0=off, 1=moderate, 2=strict)
        safe_map = {
            "off": 0,
            "medium": 1,
            "high": 2,
        }
        safe_param = safe_map.get(safe_search, 1)

        # Try multiple instances
        random.shuffle(self._instances)
        last_error = None

        for instance in self._instances[:3]:  # Try up to 3 instances
            try:
                result = await self._search_instance(
                    instance, query, num_results, safe_param
                )
                if result.success and result.images:
                    return result
                last_error = result.error
            except Exception as e:
                last_error = str(e)
                log.warning(f"Instance {instance} failed: {e}")
                continue

        return ImageSearchResult(
            success=False,
            query=query,
            images=[],
            total_results=0,
            error=last_error or "All search instances failed"
        )

    async def _search_instance(
        self,
        instance: str,
        query: str,
        num_results: int,
        safe_search: int
    ) -> ImageSearchResult:
        """Search a specific SearXNG instance."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }

        params = {
            "q": query,
            "categories": "images",
            "format": "json",
            "safesearch": safe_search,
        }

        async with aiohttp.ClientSession() as session:
            url = f"{instance}/search"
            async with session.get(
                url,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return ImageSearchResult(
                        success=False,
                        query=query,
                        images=[],
                        total_results=0,
                        error=f"{instance}: HTTP {resp.status}"
                    )

                data = await resp.json()

        # Parse results
        images = []
        results = data.get("results", [])

        for item in results[:num_results]:
            # SearXNG returns different fields for images
            img_url = item.get("img_src") or item.get("thumbnail_src") or item.get("url", "")

            if not img_url or not img_url.startswith("http"):
                continue

            images.append(ImageResult(
                url=img_url,
                title=item.get("title", "No title"),
                source_url=item.get("url", ""),
                width=item.get("img_format", "").split("x")[0] if "x" in str(item.get("img_format", "")) else 0,
                height=item.get("img_format", "").split("x")[1] if "x" in str(item.get("img_format", "")) else 0,
            ))

        if not images:
            return ImageSearchResult(
                success=False,
                query=query,
                images=[],
                total_results=0,
                error=f"{instance}: No images found"
            )

        log.tree("Image Search Complete", [
            ("Instance", instance),
            ("Results", len(images)),
        ], emoji="✅")

        return ImageSearchResult(
            success=True,
            query=query,
            images=images,
            total_results=len(images),
        )


# Global instance
image_service = ImageService()
