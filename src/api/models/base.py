"""
TrippixnBot - Base API Models
=============================

Base Pydantic models for API responses.

Author: حَـــــنَّـــــا
"""

from typing import Generic, TypeVar, Optional
from pydantic import BaseModel

T = TypeVar("T")


class APIResponse(BaseModel, Generic[T]):
    """Standard API response wrapper."""

    success: bool = True
    message: Optional[str] = None
    data: Optional[T] = None


__all__ = ["APIResponse"]
