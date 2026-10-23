"""Population API endpoints.

This module provides endpoints for listing populations, retrieving
population details, and accessing contact matrices.
"""

from fastapi import APIRouter, Body, HTTPException, Path, Query

from ....services import population_service
from ....services.population_service import PopulationLoadTimeoutError
from ....services.python_export import (
    render_contacts_python,
    render_custom_population_python,
    render_population_list_python,
    render_population_python,
)
from ...responses import PythonSourceResponse, python_source_response
from ..schemas.common import CacheInfoResponse
from ..schemas.population import (
    ContactMatrixResponse,
    PopulationDetail,
    PopulationListResponse,
)
from ..schemas.simulation import CustomPopulationConfig

router = APIRouter()


_UNITED_STATES_DETAIL_EXAMPLE = {
    "name": "United_States",
    "display_name": "United States",
    "total_population": 338120586,
    "age_groups": {
        "0-4": 18608139,
        "5-19": 63540783,
        "20-49": 132780169,
        "50-64": 63172279,
        "65+": 60019216,
    },
    "age_distribution": {
        "0": 3667336,
        "1": 3713583,
        "2": 3630098,
        "3": 3767485,
        "4": 3829637,
        "5": 3917291,
        "6": 3996031,
        "7": 4101044,
        "8": 4137919,
        "9": 4126760,
        "10": 4114032,
        "11": 4121711,
        "12": 4166827,
        "13": 4253423,
        "14": 4343515,
        "15": 4508132,
        "16": 4502791,
        "17": 4432925,
        "18": 4395762,
        "19": 4422620,
        "20": 4382209,
        "21": 4362527,
        "22": 4444906,
        "23": 4448980,
        "24": 4379763,
        "25": 4373287,
        "26": 4383880,
        "27": 4412562,
        "28": 4488035,
        "29": 4580433,
        "30": 4651049,
        "31": 4752388,
        "32": 4819745,
        "33": 4828939,
        "34": 4688811,
        "35": 4600864,
        "36": 4545592,
        "37": 4550786,
        "38": 4542751,
        "39": 4432127,
        "40": 4349752,
        "41": 4236657,
        "42": 4157608,
        "43": 4171773,
        "44": 4127247,
        "45": 4109017,
        "46": 4117218,
        "47": 4116783,
        "48": 4162103,
        "49": 4213180,
        "50": 4126472,
        "51": 4086715,
        "52": 4117683,
        "53": 4150925,
        "54": 4181148,
        "55": 4238075,
        "56": 4265036,
        "57": 4310175,
        "58": 4335272,
        "59": 4282817,
        "60": 4214078,
        "61": 4238440,
        "62": 4241499,
        "63": 4215604,
        "64": 4168338,
        "65": 4098795,
        "66": 3985170,
        "67": 3864440,
        "68": 3732717,
        "69": 3612801,
        "70": 3338420,
        "71": 3113775,
        "72": 2947849,
        "73": 2778812,
        "74": 2563739,
        "75": 2204521,
        "76": 1990194,
        "77": 1878879,
        "78": 1717196,
        "79": 1540790,
        "80": 1369057,
        "81": 1243538,
        "82": 1113300,
        "83": 999890,
        "84+": 7418335,
    },
    "contact_sources": ["prem_2017", "prem_2021", "mistry_2021"],
    "default_contact_source": "mistry_2021",
    "available_layers": ["home", "work", "school", "community"],
}


@router.get(
    "",
    response_model=PopulationListResponse,
    summary="List available populations",
    description="Get a list of all available populations that can be used in simulations.",
    operation_id="list_populations",
)
async def get_populations() -> PopulationListResponse:
    """List all available populations.

    Returns a summary of each population including name and available
    contact sources from the epydemix data repository.

    Returns
    -------
    PopulationListResponse
        List of population summaries with total count.

    Raises
    ------
    HTTPException
        500 if population listing fails.
    """
    try:
        return population_service.list_populations()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list populations: {str(e)}")


@router.get(
    "/export/python",
    response_class=PythonSourceResponse,
    summary="Export population listing as Python",
    operation_id="export_population_list_python",
)
async def export_population_list_python(
    attribute: str = Query(default="age"),
    level: int | None = Query(default=None),
) -> PythonSourceResponse:
    """Export Python that lists available epydemix populations."""
    return python_source_response(
        render_population_list_python(attribute, level), "list_populations.py"
    )


@router.post(
    "/export/python",
    response_class=PythonSourceResponse,
    summary="Export a custom population as Python",
    operation_id="export_custom_population_python",
)
async def export_custom_population_python(
    config: CustomPopulationConfig = Body(...),
) -> PythonSourceResponse:
    """Export Python that constructs an inline custom population."""
    return python_source_response(
        render_custom_population_python(config), "custom_population.py"
    )


@router.get(
    "/cache",
    response_model=CacheInfoResponse,
    summary="Get population cache status",
    description="Get information about the population cache.",
    operation_id="get_population_cache_status",
)
async def get_cache_status() -> CacheInfoResponse:
    """Get population cache status.

    Returns cache statistics including hits, misses, and list of
    cached populations.

    Returns
    -------
    CacheInfoResponse
        Cache statistics and list of cached populations.
    """
    info = population_service.get_cache_info()
    return CacheInfoResponse(**info)


@router.get(
    "/{name}/export/python",
    response_class=PythonSourceResponse,
    summary="Export population loading as Python",
    operation_id="export_population_python",
)
async def export_population_python(
    name: str,
    contacts_source: str | None = Query(default=None),
) -> PythonSourceResponse:
    """Export Python that loads and inspects one population."""
    return python_source_response(
        render_population_python(name, contacts_source), f"{name}_population.py"
    )


@router.get(
    "/{name}/contacts/export/python",
    response_class=PythonSourceResponse,
    summary="Export contact-matrix loading as Python",
    operation_id="export_population_contacts_python",
)
async def export_population_contacts_python(
    name: str,
    contacts_source: str | None = Query(default=None),
    layers: list[str] | None = Query(default=None),
) -> PythonSourceResponse:
    """Export Python that loads and inspects contact matrices."""
    return python_source_response(
        render_contacts_python(name, contacts_source, layers), f"{name}_contacts.py"
    )


@router.get(
    "/{name}",
    response_model=PopulationDetail,
    summary="Get population details",
    description=(
        "Get detailed information about a specific population, including total population, "
        "population by default age groups, the raw per-single-year age distribution, "
        "available contact matrix sources, the default source, and available contact layers."
    ),
    operation_id="get_population",
    responses={
        200: {
            "content": {
                "application/json": {
                    "examples": {
                        "United_States": {
                            "summary": "United States",
                            "value": _UNITED_STATES_DETAIL_EXAMPLE,
                        }
                    }
                }
            }
        }
    },
)
async def get_population(
    name: str = Path(
        ...,
        description="Population identifier (e.g. `United_States`).",
        openapi_examples={"United_States": {"summary": "United States", "value": "United_States"}},
    ),
    contacts_source: str | None = Query(
        default=None,
        description="Contact matrix source (prem_2017, prem_2021, or mistry_2021)",
    ),
) -> PopulationDetail:
    """Get detailed information about a population.

    Returns total population, the default 5-group age aggregation, the raw
    per-single-year age distribution, available contact matrix sources, the
    default source, and available contact layers.

    Parameters
    ----------
    name : str
        Population identifier (e.g., 'United_States').
    contacts_source : str or None, optional
        Contact matrix source to use. If None, uses the default.

    Returns
    -------
    PopulationDetail
        Detailed population information.

    Raises
    ------
    HTTPException
        404 if population not found, 504 if timeout, 500 if retrieval fails.
    """
    try:
        return population_service.get_population_detail(name, contacts_source)
    except PopulationLoadTimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get population: {str(e)}")


@router.get(
    "/{name}/contacts",
    response_model=ContactMatrixResponse,
    summary="Get contact matrices",
    description="Get contact matrices for a specific population.",
    operation_id="get_population_contacts",
)
async def get_contact_matrices(
    name: str,
    contacts_source: str | None = Query(
        default=None,
        description="Contact matrix source (prem_2017, prem_2021, or mistry_2021)",
    ),
    layers: list[str] | None = Query(
        default=None,
        description="Contact layers to include (e.g., home, work, school, community)",
    ),
) -> ContactMatrixResponse:
    """Get contact matrices for a population.

    Returns contact matrices for each specified layer (home, work, school,
    community) as well as the overall combined matrix.

    Parameters
    ----------
    name : str
        Population identifier (e.g., 'United_States').
    contacts_source : str or None, optional
        Contact matrix source. If None, uses the default.
    layers : list of str or None, optional
        Contact layers to include. If None, includes all layers.

    Returns
    -------
    ContactMatrixResponse
        Contact matrices by layer and combined overall matrix.

    Raises
    ------
    HTTPException
        404 if population not found, 504 if timeout, 500 if retrieval fails.
    """
    try:
        return population_service.get_contact_matrices(name, contacts_source, layers)
    except PopulationLoadTimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get contacts: {str(e)}")
