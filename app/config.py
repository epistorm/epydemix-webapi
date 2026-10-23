"""Application configuration settings.

This module defines the Settings class which loads configuration from
environment variables with the EPYDEMIX_ prefix.
"""

from importlib.metadata import PackageNotFoundError, version

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

try:
    _APP_VERSION = version("epydemix-webapi")
except PackageNotFoundError:
    _APP_VERSION = "0.0.0"


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All settings can be overridden by environment variables with the
    EPYDEMIX_ prefix (e.g., EPYDEMIX_DEBUG=true).

    Attributes
    ----------
    app_name : str
        Application display name.
    app_version : str
        Application version string.
    debug : bool
        Enable debug mode.
    api_v1_prefix : str
        URL prefix for API v1 endpoints.
    default_nsim : int
        Default number of simulations if not specified.
    max_nsim : int
        Maximum allowed number of simulations.
    default_dt : float
        Default time step in days.
    """

    model_config = SettingsConfigDict(env_prefix="EPYDEMIX_")

    app_name: str = "epydemix WebAPI"
    app_version: str = _APP_VERSION
    debug: bool = False

    # API settings
    api_v1_prefix: str = "/api/v1"

    # Simulation defaults
    default_nsim: int = Field(default=10, ge=1, le=1000)
    max_nsim: int = Field(default=1000, ge=1, le=1000)
    default_dt: float = Field(default=1.0, gt=0, allow_inf_nan=False)

    # Cache settings
    warm_cache_on_startup: bool = True
    warm_cache_populations: list[str] | None = None  # None = use defaults

    # Timeout settings (seconds)
    population_load_timeout: float = Field(default=30.0, gt=0, allow_inf_nan=False)
    request_timeout: float = Field(default=60.0, gt=0, allow_inf_nan=False)
    # Per-worker admission and pre-allocation budgets.
    max_simulation_steps: int = Field(default=10000, ge=3)
    max_simulation_cells: int = Field(default=10000000, ge=1)
    max_contact_cells: int = Field(default=2000000, ge=1)

    # MCP server (Model Context Protocol) — exposes API endpoints as agent tools at /mcp
    mcp_enabled: bool = True


settings = Settings()
