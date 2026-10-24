"""Simulation API endpoints.

This module provides the endpoint for running epidemic simulations.
"""

import logging

from fastapi import APIRouter, Body, HTTPException
from fastapi.openapi.models import Example

from ....services.population_service import PopulationLoadTimeoutError
from ....services.python_export import render_simulation_python
from ....services.simulation_runtime import (
    SimulationBusyError,
    SimulationTimeoutError,
    run_simulation,
)
from ...responses import PythonSourceResponse, python_source_response
from ..schemas.simulation import SimulationRequest, SimulationResponse

logger = logging.getLogger(__name__)

router = APIRouter()

SIMULATION_REQUEST_EXAMPLES: dict[str, Example] = {
    "SIR": Example(
        summary="Basic SIR simulation",
        description="Run a Susceptible-Infected-Recovered model on the US population over two months.",
        value={
            "model": {
                "preset": "SIR",
                "parameters": {"R0": 2.5, "recovery_rate": 0.1},
            },
            "population": {"name": "United_States"},
            "simulation": {
                "start_date": "2024-01-01",
                "end_date": "2024-03-01",
                "Nsim": 10,
            },
        },
    ),
    "SIR in custom population (homogeneous)": Example(
        summary="SIR on a custom inline population",
        description=(
            "Single-group population of 100,000 with a 1x1 contact matrix specified "
            "inline. No epydemix data repo lookup; `age_groups` insertion order "
            "defines the contact-matrix row/col order."
        ),
        value={
            "model": {
                "preset": "SIR",
                "parameters": {"transmission_rate": 0.3, "recovery_rate": 0.1},
            },
            "population": {
                "source": "custom",
                "name": "Custom Population 1",
                "age_groups": {"A": 100000},
                "contact_matrices": {"all": [[1.0]]},
            },
            "simulation": {
                "start_date": "2024-01-01",
                "end_date": "2024-03-01",
                "Nsim": 5,
            },
        },
    ),
    "V-SEIHR with seasonality and vaccination": Example(
        summary="V-SEIHR: Northern-Hemisphere seasonality + autumn vaccination campaign",
        description=(
            "Year-long V-SEIHR run on the US population with two interventions composed: "
            "seasonality on `transmission_rate` (peak Jan 15, trough Jul 15, "
            "matching the Northern Hemisphere defaults from Balcan et al. 2010, "
            "https://doi.org/10.1016/j.jocs.2010.07.002), and a flat-count vaccination "
            "campaign delivered Oct 15 - Dec 31 so the rollout finishes just before "
            "the seasonal peak. `output.include_parameters` is enabled so the per-step "
            "`transmission_rate` series surfaces in the response for sanity-checking "
            "the envelope."
        ),
        value={
            "model": {
                "preset": "V-SEIHR",
                "parameters": {
                    "R0": 2.5,
                    "incubation_period": 3.0,
                    "infectious_period": 2.5,
                    "hosp_duration": 5.0,
                    "hosp_proportion": [0.002, 0.005, 0.015, 0.05, 0.18],
                    "VE_S": 0.7,
                    "VE_H": 0.85,
                },
            },
            "population": {"name": "United_States"},
            "simulation": {
                "start_date": "2025-08-01",
                "end_date": "2026-07-31",
                "Nsim": 10,
            },
            "parameter_transforms": [
                {
                    "target_parameter": "transmission_rate",
                    "method": "balcan",
                    "max_date": "2026-01-15",
                    "min_date": "2026-07-15",
                    "min_value": 0.85,
                }
            ],
            "vaccination": {
                "campaigns": [
                    {
                        "start_date": "2025-10-15",
                        "end_date": "2025-12-31",
                        "rollout": {"type": "flat_count", "daily_doses": 100000},
                    }
                ]
            },
            "output": {"include_parameters": True},
        },
    ),
}


@router.post(
    "",
    response_model=SimulationResponse,
    summary="Run epidemic simulation",
    description="Execute an epidemic simulation with the specified configuration.",
    operation_id="run_simulation",
)
def create_simulation(
    request: SimulationRequest = Body(..., openapi_examples=SIMULATION_REQUEST_EXAMPLES),
) -> SimulationResponse:
    """Run an epidemic simulation.

    Accepts a simulation configuration and returns results including
    compartment trajectories, transitions, and optional summary statistics.

    The simulation can use predefined model presets (SIR, SEIR, SIS) or
    custom compartmental models defined by the user.

    Parameters
    ----------
    request : SimulationRequest
        Complete simulation configuration including model, population,
        simulation parameters, and output options.

    Returns
    -------
    SimulationResponse
        Simulation results with compartment and transition data.

    Raises
    ------
    HTTPException
        422 if the configuration is invalid, 504 if loading the population
        times out, 500 on an unexpected internal error.
    """
    try:
        return run_simulation(request)
    except SimulationBusyError as e:
        raise HTTPException(status_code=503, detail=str(e), headers={"Retry-After": "1"})
    except SimulationTimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except PopulationLoadTimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("Simulation failed")
        raise HTTPException(status_code=500, detail="Simulation failed due to an internal error.")


@router.post(
    "/export/python",
    response_class=PythonSourceResponse,
    summary="Export a simulation as Python",
    description=(
        "Render the simulation request as a standalone Python program that calls "
        "epydemix directly. The simulation is not executed on the server."
    ),
    operation_id="export_simulation_python",
)
def export_simulation_python(
    request: SimulationRequest = Body(..., openapi_examples=SIMULATION_REQUEST_EXAMPLES),
) -> PythonSourceResponse:
    """Export a validated simulation request as executable Python."""
    try:
        source = render_simulation_python(request)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return python_source_response(source, "epydemix_simulation.py")
