"""Population data service for accessing epydemix population information.

This module provides functions for listing available populations,
retrieving population details, and accessing contact matrices.
"""

import copy
import functools
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path

import numpy as np
from epydemix.population.population import (
    Population,
    get_available_locations,
    load_epydemix_population,
)

from epydemix.model.epimodel import EpiModel

from ..api.v1.schemas.population import (
    ContactMatrixResponse,
    PopulationDetail,
    PopulationListResponse,
    PopulationSummary,
)
from ..api.v1.schemas.simulation import CustomPopulationConfig, PopulationConfig
from ..api.v1.schemas.simulation.request import DEFAULT_LAYERS
from ..config import settings

logger = logging.getLogger(__name__)


class PopulationLoadTimeoutError(Exception):
    """Raised when population loading exceeds the configured timeout."""

    def __init__(self, population_name: str, timeout: float):
        self.population_name = population_name
        self.timeout = timeout
        super().__init__(f"Loading population '{population_name}' timed out after {timeout}s")


@functools.lru_cache(maxsize=1)
def get_locations_df():
    """Get the locations dataframe from epydemix.

    Results are cached to avoid repeated network/disk fetches.

    Returns
    -------
    pd.DataFrame
        DataFrame containing available locations and their metadata.
    """
    return get_available_locations()


# Cache of per-population metadata (total_population, age_groups).
# Seeded from the precomputed CSV at module import; subsequent live loads
# (via _load_population_cached) keep it up to date.
_population_metadata_cache: dict[str, dict] = {}

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_PRECOMPUTED_METADATA_PATH = _DATA_DIR / "population_metadata.csv"
_PRECOMPUTED_AGE_DISTRIBUTION_PATH = _DATA_DIR / "population_age_distribution.csv"


def _read_long_csv(path: Path, label_column: str) -> dict[str, dict[str, int]]:
    """Read a ``name,<label>,population`` CSV into ``{name: {label: population}}``.

    Preserves row-insertion order within each population so downstream consumers
    can rely on age-ascending ordering if the file was written that way.
    """
    import csv

    result: dict[str, dict[str, int]] = {}
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["name"]
            result.setdefault(name, {})[row[label_column]] = int(row["population"])
    return result


def _load_precomputed_metadata(
    aggregated_path: Path = _PRECOMPUTED_METADATA_PATH,
    raw_path: Path = _PRECOMPUTED_AGE_DISTRIBUTION_PATH,
) -> None:
    """Seed ``_population_metadata_cache`` from the precomputed CSVs.

    ``aggregated_path`` carries the default 5-group ``age_groups`` per population.
    ``raw_path`` carries the raw single-year ``age_distribution``. Either file
    missing just means those fields stay empty until the relevant population is
    loaded on demand.
    """
    if aggregated_path.exists():
        age_groups_by_name = _read_long_csv(aggregated_path, "age_group")
        for name, age_groups in age_groups_by_name.items():
            entry = _population_metadata_cache.setdefault(name, {})
            entry["total_population"] = sum(age_groups.values())
            entry["age_groups"] = age_groups
        logger.info(
            "Loaded precomputed aggregated metadata for %d populations from %s",
            len(age_groups_by_name),
            aggregated_path.name,
        )
    else:
        logger.warning("Precomputed metadata CSV not found at %s", aggregated_path)

    if raw_path.exists():
        distribution_by_name = _read_long_csv(raw_path, "age")
        for name, distribution in distribution_by_name.items():
            entry = _population_metadata_cache.setdefault(name, {})
            entry["age_distribution"] = distribution
        logger.info(
            "Loaded precomputed age distribution for %d populations from %s",
            len(distribution_by_name),
            raw_path.name,
        )
    else:
        logger.warning("Precomputed age distribution CSV not found at %s", raw_path)


_load_precomputed_metadata()


def list_populations() -> PopulationListResponse:
    """List all available populations.

    Retrieves summary information for all populations available in the
    epydemix data repository. If a population has been cached (e.g., via
    warm_cache), includes total_population and n_age_groups.

    Returns
    -------
    PopulationListResponse
        Response containing list of population summaries and total count.
    """
    df = get_locations_df()

    populations = []
    for _, row in df.iterrows():
        name = row["location"]
        # Parse available contact sources from the row if available
        available_sources = []
        for source in ["prem_2017", "prem_2021", "mistry_2021"]:
            if source in df.columns and row.get(source, False):
                available_sources.append(source)
        # If no sources found in columns, use default
        if not available_sources:
            # Check primary_contact_source column
            if "primary_contact_source" in df.columns:
                available_sources = [row["primary_contact_source"]]
            else:
                available_sources = ["mistry_2021"]

        # Get cached metadata if available
        metadata = _population_metadata_cache.get(name, {})
        total_pop = metadata.get("total_population")

        populations.append(
            PopulationSummary(
                name=name,
                display_name=str(name).replace("_", " "),
                total_population=total_pop,
                available_contact_sources=available_sources,
            )
        )

    return PopulationListResponse(populations=populations, total=len(populations))


@functools.lru_cache(maxsize=50)
def _load_population_cached_inner(name: str, contacts_source: str) -> Population:
    """Load a population with caching (internal).

    Parameters
    ----------
    name : str
        Population name (e.g., 'United_States').
    contacts_source : str
        Contact matrix source (must be resolved, not None).

    Returns
    -------
    Population
        Loaded epydemix Population object.
    """
    return load_epydemix_population(
        population_name=name,
        contacts_source=contacts_source,
    )


def _resolve_contacts_source(name: str, contacts_source: str | None) -> str:
    """Resolve contacts_source to actual value.

    Parameters
    ----------
    name : str
        Population name.
    contacts_source : str or None
        Contact source, or None to use default.

    Returns
    -------
    str
        Resolved contact source name.
    """
    if contacts_source is not None:
        return contacts_source
    # Get the default from locations.csv
    df = get_locations_df()
    row = df[df["location"] == name]
    if len(row) > 0 and "primary_contact_source" in df.columns:
        return row.iloc[0]["primary_contact_source"]
    return "mistry_2021"  # fallback default


@functools.lru_cache(maxsize=50)
def _load_population_for_sim(
    name: str,
    contacts_source: str,
    layers_key: tuple[str, ...],
    mapping_key: tuple[tuple[str, tuple[str, ...]], ...] | None,
) -> Population:
    """Cached builtin-population load for the simulation path.

    All four arguments must be hashable and canonical so equivalent requests
    hit the same cache entry: ``contacts_source`` resolved (never None),
    ``layers`` sorted, ``age_group_mapping`` flattened to sorted tuples. The
    underlying ``load_epydemix_population`` fetches ~6-7 CSVs over HTTPS with no
    cache of its own, so this collapses repeated identical loads (~0.6s each)
    to a single fetch.

    Returns the shared cached object; callers must copy before handing it to a
    model (see ``setup_population``).
    """
    mapping = {k: list(v) for k, v in mapping_key} if mapping_key is not None else None
    return load_epydemix_population(
        population_name=name,
        contacts_source=contacts_source,
        layers=list(layers_key),
        age_group_mapping=mapping,
    )


def setup_population(model: EpiModel, config: PopulationConfig) -> None:
    """Load and set population for the model.

    For builtin populations, loads from the epydemix data repository.
    For custom populations, builds a Population in-memory from the inline
    `age_groups` dict and `contact_matrices` dict.

    Parameters
    ----------
    model : EpiModel
        EpiModel to configure with population data.
    config : BuiltinPopulationConfig or CustomPopulationConfig
        Population configuration. The discriminator selects the branch.
    """
    if isinstance(config, CustomPopulationConfig):
        # Insertion order of `age_groups` defines the contact-matrix row/col order.
        names = list(config.age_groups.keys())
        sizes = [float(config.age_groups[k]) for k in names]
        population = Population(name=config.name)
        population.add_population(Nk=sizes, Nk_names=names)
        for layer_name, matrix in config.contact_matrices.items():
            population.add_contact_matrix(
                contact_matrix=np.array(matrix, dtype=float),
                layer_name=layer_name,
            )
        model.set_population(population)
        return

    # Route the builtin load through a cache keyed on the canonicalized args.
    # Resolving contacts_source collapses None and its default to one entry;
    # sorting layers makes order irrelevant (the resulting contact_matrices
    # dict is order-independent). The cache hands back a shared object, so we
    # deepcopy before binding it to this request's model to rule out any
    # cross-request mutation (cheap: a handful of small arrays).
    resolved_source = _resolve_contacts_source(config.name, config.contacts_source)
    layers_key = tuple(sorted(config.layers or DEFAULT_LAYERS))
    mapping = config.age_group_mapping
    mapping_key = (
        tuple(sorted((k, tuple(v)) for k, v in mapping.items()))
        if mapping is not None
        else None
    )
    population = _load_population_for_sim(
        config.name, resolved_source, layers_key, mapping_key
    )
    model.set_population(copy.deepcopy(population))


def _load_population_cached(
    name: str,
    contacts_source: str | None = None,
    timeout: float | None = None,
) -> Population:
    """Load a population with caching and optional timeout.

    Normalizes contacts_source before caching to avoid duplicate cache entries
    for None vs explicit default value. Also populates the metadata cache.

    Parameters
    ----------
    name : str
        Population name (e.g., 'United_States').
    contacts_source : str or None, optional
        Contact matrix source. If None, uses the default for the population.
    timeout : float or None, optional
        Maximum time in seconds to wait for loading. If None, uses config default.
        Only applies to cache misses (cached loads are instant).

    Returns
    -------
    Population
        Loaded epydemix Population object.

    Raises
    ------
    PopulationLoadTimeoutError
        If loading exceeds the timeout.
    """
    resolved_source = _resolve_contacts_source(name, contacts_source)

    if timeout is None:
        timeout = settings.population_load_timeout

    # Use ThreadPoolExecutor to enforce timeout on the load
    # Note: If already cached, the load is instant so timeout won't trigger
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_load_population_cached_inner, name, resolved_source)
        try:
            pop = future.result(timeout=timeout)
        except FuturesTimeoutError:
            future.cancel()
            raise PopulationLoadTimeoutError(name, timeout)

    # Update metadata cache. Preserve any precomputed fields (e.g. age_distribution).
    entry = _population_metadata_cache.setdefault(name, {})
    entry["total_population"] = int(pop.total_population)
    entry["age_groups"] = {str(label): int(count) for label, count in zip(pop.Nk_names, pop.Nk)}

    return pop


def get_population_detail(name: str, contacts_source: str | None = None) -> PopulationDetail:
    """Get detailed information about a population.

    Loads the population and returns comprehensive information including
    demographics, age groups, and available contact sources.

    Parameters
    ----------
    name : str
        Population name (e.g., 'United_States').
    contacts_source : str or None, optional
        Contact matrix source to use when loading. If None, uses default.

    Returns
    -------
    PopulationDetail
        Detailed population information including age groups and contact sources.

    Raises
    ------
    ValueError
        If the population name is not found.
    """
    pop = _load_population_cached(name, contacts_source)

    age_groups = {str(ag_name): int(pop_count) for ag_name, pop_count in zip(pop.Nk_names, pop.Nk)}

    # Get available contact sources from locations df
    df = get_locations_df()
    row = df[df["location"] == name].iloc[0] if len(df[df["location"] == name]) > 0 else None

    available_sources = []
    default_source = None
    if row is not None:
        for source in ["prem_2017", "prem_2021", "mistry_2021"]:
            if source in df.columns and row.get(source, False):
                available_sources.append(source)
        if "primary_contact_source" in df.columns:
            default_source = row["primary_contact_source"]

    if not available_sources:
        available_sources = ["mistry_2021"]

    age_distribution = _population_metadata_cache.get(name, {}).get("age_distribution", {})

    return PopulationDetail(
        name=name,
        display_name=name.replace("_", " "),
        total_population=int(pop.total_population),
        age_groups=age_groups,
        age_distribution=age_distribution,
        contact_sources=available_sources,
        default_contact_source=default_source,
        available_layers=pop.layers,
    )


def _compute_spectral_radius(matrix: np.ndarray) -> float:
    """Compute the spectral radius of a matrix.

    The spectral radius is the largest absolute eigenvalue of the matrix.
    For contact matrices, this is related to the basic reproduction number (R0).

    Parameters
    ----------
    matrix : np.ndarray
        Square matrix to compute spectral radius for.

    Returns
    -------
    float
        The spectral radius (largest absolute eigenvalue).
    """
    eigenvalues = np.linalg.eigvals(matrix)
    return float(np.max(np.abs(eigenvalues.real)))


def get_contact_matrices(
    name: str,
    contacts_source: str | None = None,
    layers: list[str] | None = None,
) -> ContactMatrixResponse:
    """Get contact matrices for a population.

    Returns contact matrices for specified layers as well as the combined
    overall contact matrix, along with spectral radii.

    Parameters
    ----------
    name : str
        Population name (e.g., 'United_States').
    contacts_source : str or None, optional
        Contact matrix source. If None, uses the default for the population.
    layers : list of str or None, optional
        Contact layers to include. If None, includes all available layers.

    Returns
    -------
    ContactMatrixResponse
        Contact matrices by layer, combined overall matrix, and spectral radii.

    Raises
    ------
    ValueError
        If the population name is not found.
    """
    pop = _load_population_cached(name, contacts_source)

    # Filter layers if specified
    layer_names = layers if layers else pop.layers
    matrices = {}
    spectral_radii = {}

    for layer in layer_names:
        if layer in pop.contact_matrices:
            matrix = pop.contact_matrices[layer]
            matrices[layer] = matrix.tolist()
            spectral_radii[layer] = _compute_spectral_radius(matrix)

    # Compute overall matrix and its spectral radius
    overall = None
    if matrices:
        overall_matrix = np.zeros_like(list(pop.contact_matrices.values())[0])
        for layer in layer_names:
            if layer in pop.contact_matrices:
                overall_matrix += pop.contact_matrices[layer]
        overall = overall_matrix.tolist()
        spectral_radii["overall"] = _compute_spectral_radius(overall_matrix)

    return ContactMatrixResponse(
        population_name=name,
        contact_source=contacts_source or "default",
        layers=matrices,
        overall=overall,
        age_groups=[str(ag) for ag in pop.Nk_names],
        spectral_radius=spectral_radii,
    )


# Default populations to pre-warm on startup
DEFAULT_WARM_POPULATIONS = [
    "United_States",
    "Italy",
    "United_Kingdom",
    "Germany",
    "France",
    "Spain",
    "Canada",
    "Australia",
    "Japan",
    "Brazil",
]


def warm_cache(
    populations: list[str] | None = None,
    max_workers: int = 4,
) -> dict[str, bool]:
    """Pre-warm the population cache for faster subsequent requests.

    Loads specified populations in parallel to populate both the lru_cache
    and the metadata cache.

    Parameters
    ----------
    populations : list of str or None, optional
        Population names to warm. If None, uses DEFAULT_WARM_POPULATIONS.
    max_workers : int, optional
        Maximum number of concurrent threads for loading. Default is 4.

    Returns
    -------
    dict[str, bool]
        Dictionary mapping population names to success status.
    """
    if populations is None:
        populations = DEFAULT_WARM_POPULATIONS

    results: dict[str, bool] = {}

    def load_one(name: str) -> tuple[str, bool]:
        try:
            _load_population_cached(name, None)
            return (name, True)
        except Exception as e:
            logger.warning(f"Failed to warm cache for {name}: {e}")
            return (name, False)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(load_one, name): name for name in populations}
        for future in as_completed(futures):
            name, success = future.result()
            results[name] = success
            if success:
                logger.info(f"Warmed cache for {name}")

    return results


def get_cache_info() -> dict:
    """Get information about the current cache state.

    Returns
    -------
    dict
        Cache statistics including hits, misses, and cached populations.
    """
    cache_info = _load_population_cached_inner.cache_info()
    return {
        "hits": cache_info.hits,
        "misses": cache_info.misses,
        "maxsize": cache_info.maxsize,
        "currsize": cache_info.currsize,
        "cached_populations": list(_population_metadata_cache.keys()),
    }
