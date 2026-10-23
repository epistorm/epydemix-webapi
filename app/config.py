"""Application configuration settings.

This module defines the Settings class which loads configuration from
environment variables with the EPYDEMIX_ prefix.
"""

from importlib.metadata import PackageNotFoundError, version

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
    default_nsim: int = 100
    max_nsim: int = 1000
    default_dt: float = 1.0

    # Cache settings
    warm_cache_on_startup: bool = True
    warm_cache_populations: list[str] | None = None  # None = use defaults

    # Timeout settings (seconds)
    population_load_timeout: float = 30.0  # Max time to load a single population
    request_timeout: float = 60.0  # Max time for any API request

    # MCP server (Model Context Protocol) — exposes API endpoints as agent tools at /mcp
    mcp_enabled: bool = True


settings = Settings()
