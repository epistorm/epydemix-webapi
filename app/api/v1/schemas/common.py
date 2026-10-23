"""Common schema definitions used across the API.

This module defines shared response schemas used by multiple endpoints.
"""

from datetime import date
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field


def _check_date(value: str) -> str:
    """Accept only real calendar dates written as ``YYYY-MM-DD``."""
    try:
        valid = date.fromisoformat(value).isoformat() == value
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"'{value}' is not a valid date in YYYY-MM-DD format")
    return value


DateStr = Annotated[str, AfterValidator(_check_date)]


class ErrorResponse(BaseModel):
    """Standard error response schema."""

    detail: str = Field(
        ...,
        description="Human-readable error message.",
        examples=["Population 'Mars' not found."],
    )


class HealthResponse(BaseModel):
    """Health check response schema."""

    status: str = Field(..., description="Health status.", examples=["healthy"])
    version: str = Field(..., description="API version string.", examples=["0.2.2"])
    epydemix_version: str | None = Field(
        default=None,
        description="Version of the epydemix library, or None if not available.",
        examples=["0.3.4"],
    )


class CacheInfoResponse(BaseModel):
    """Cache information response schema."""

    hits: int = Field(..., description="Number of cache hits.", examples=[42])
    misses: int = Field(..., description="Number of cache misses.", examples=[8])
    maxsize: int = Field(..., description="Maximum cache size.", examples=[50])
    currsize: int = Field(..., description="Current number of cached items.", examples=[10])
    cached_populations: list[str] = Field(
        ...,
        description="Names of populations currently in cache.",
        examples=[["United_States", "Italy", "Germany"]],
    )
