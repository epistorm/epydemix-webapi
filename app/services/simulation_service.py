"""End-to-end simulation orchestration.

This module sequences the pre-run pipeline (model construction, population
loading, parameter transforms, calculated parameters, vaccination flows),
runs the epydemix simulator, and assembles the response. The individual
stages live in sibling service modules:

- ``model_service``: model construction, age-varying / calculated parameters,
  initial conditions, interventions, parameter-results extraction.
- ``population_service``: population loading (``setup_population``).
- ``parameter_transforms_service``: source-pass and calc-pass transforms.
- ``vaccination_service``: vaccination campaigns and dose competition.
- ``results_processing``: trajectory and summary post-processing.
"""

import uuid

import numpy as np
import pandas as pd
from epydemix.model.simulation_results import SimulationResults

from ..api.v1.schemas.simulation import (
    CustomPopulationConfig,
    ModelMetadata,
    ParameterResults,
    PopulationConfig,
    PopulationMetadata,
    SimulationConfig,
    SimulationMetadata,
    SimulationRequest,
    SimulationResponse,
    SimulationRunMetadata,
)
from ..presets import PRESETS
from ..utils.calculated_parameters import RESERVED_NAMES
from ..utils.parameter_conversions import resolve_parameter_conversions
from .model_service import (
    apply_age_varying_parameters,
    apply_calculated_parameters,
    apply_interventions,
    create_initial_conditions,
    create_model,
    extract_parameter_results,
)
from .parameter_transforms_service import (
    apply_parameter_transforms_calc,
    apply_parameter_transforms_sources,
)
from .population_service import DEFAULT_LAYERS, _resolve_contacts_source, setup_population
from .results_processing import process_results
from .vaccination_service import apply_vaccinations


def _padded_internal_simulation(sim: SimulationConfig) -> SimulationConfig:
    """Return a simulation config padded by one calendar day when ``dt < 1``.

    Works around epydemix's partial-last-day aggregation bug/design: with sub-daily ``dt`` and daily resampling, the user-requested ``end_date`` only gets one
    sub-step instead of ``1/dt``, so summed transitions on that day are scaled
    by ``dt``. Padding ``end_date`` by one day lets the originally-requested
    last day collect its full set of sub-steps; ``_trim_results_to_end_date``
    drops the padded tail before the response is built.
    """
    if sim.dt >= 1.0:
        return sim
    padded_end = (pd.Timestamp(sim.end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return sim.model_copy(update={"end_date": padded_end})


def _trim_results_to_end_date(results: SimulationResults, user_end_date: str) -> None:
    """Drop trailing dates past ``user_end_date`` from every trajectory in-place."""
    cutoff = pd.Timestamp(user_end_date).normalize()
    for traj in results.trajectories:
        n_keep = sum(1 for d in traj.dates if pd.Timestamp(d).normalize() <= cutoff)
        if n_keep == len(traj.dates):
            continue
        traj.dates = traj.dates[:n_keep]
        traj.compartments = {k: v[:n_keep] for k, v in traj.compartments.items()}
        traj.transitions = {k: v[:n_keep] for k, v in traj.transitions.items()}


def _trim_parameter_results(params: ParameterResults, user_end_date: str) -> ParameterResults:
    """Drop trailing dates past ``user_end_date`` from a ParameterResults block."""
    cutoff = pd.Timestamp(user_end_date).normalize()
    n_keep = sum(1 for d in params.dates if pd.Timestamp(d).normalize() <= cutoff)
    if n_keep == len(params.dates):
        return params
    trimmed_data = {
        name: {grp: values[:n_keep] for grp, values in groups.items()}
        for name, groups in params.data.items()
    }
    return ParameterResults(dates=params.dates[:n_keep], data=trimmed_data)


def _build_population_metadata(
    request_population: PopulationConfig,
    model_population,
) -> PopulationMetadata:
    """Build PopulationMetadata from the request and the loaded model population."""
    age_groups = {
        str(name): int(count) for name, count in zip(model_population.Nk_names, model_population.Nk)
    }
    contact_matrices = {
        str(layer): np.asarray(matrix, dtype=float).tolist()
        for layer, matrix in (model_population.contact_matrices or {}).items()
    }
    if isinstance(request_population, CustomPopulationConfig):
        return PopulationMetadata(
            source="custom",
            name=request_population.name,
            contacts_source=None,
            layers=list(request_population.contact_matrices.keys()),
            age_group_mapping=None,
            total=int(model_population.total_population),
            age_groups=age_groups,
            contact_matrices=contact_matrices,
        )
    return PopulationMetadata(
        source="builtin",
        name=request_population.name,
        contacts_source=_resolve_contacts_source(
            request_population.name, request_population.contacts_source
        ),
        layers=request_population.layers or DEFAULT_LAYERS,
        age_group_mapping=request_population.age_group_mapping,
        total=int(model_population.total_population),
        age_groups=age_groups,
        contact_matrices=contact_matrices,
    )


def _build_run_metadata(request: SimulationRequest) -> SimulationRunMetadata:
    """Build SimulationRunMetadata from the request."""
    return SimulationRunMetadata(
        start_date=request.simulation.start_date,
        end_date=request.simulation.end_date,
        Nsim=request.simulation.Nsim,
        dt=request.simulation.dt,
        seed=request.simulation.seed,
        resample_frequency=request.simulation.resample_frequency,
    )


def run_simulation(request: SimulationRequest) -> SimulationResponse:
    """Run an epidemic simulation based on the request configuration.

    This is the main orchestration function that executes the full
    simulation workflow:

    1. Creates and configures the epidemic model
    2. Loads and sets the population
    3. Applies interventions and parameter overrides
    4. Runs the stochastic simulations
    5. Processes and returns results

    Parameters
    ----------
    request : SimulationRequest
        Complete simulation request containing model, population,
        simulation parameters, and output configuration.

    Returns
    -------
    SimulationResponse
        Response containing simulation results with compartment and
        transition trajectories, metadata, and optional summary statistics.

    Raises
    ------
    ValueError
        If the configuration is invalid for the resolved model or population.
    PopulationLoadTimeoutError
        If loading a builtin population times out.
    """
    simulation_id = f"sim_{uuid.uuid4().hex[:12]}"

    internal_sim = _padded_internal_simulation(request.simulation)

    # Reject any user parameter name that collides with a reserved
    # SCREAMING_SNAKE_CASE name (e.g. CONTACT_MATRIX_EIGENVALUE_ALL).
    # These are computed from the model state and injected into the
    # eval namespace by `apply_calculated_parameters`; allowing a
    # user override would silently mask the model-derived value.
    user_param_names = set((request.model.parameters or {}).keys())
    reserved_collisions = user_param_names & RESERVED_NAMES
    if reserved_collisions:
        raise ValueError(
            f"Parameter name(s) {sorted(reserved_collisions)} collide with "
            f"reserved name(s) injected by the calculated-parameter evaluator. "
            f"Reserved names are SCREAMING_SNAKE_CASE constants derived from "
            f"the model state and cannot be overridden."
        )

    # Create model (scalar params applied; age-varying and expression
    # params are deferred: the former until population is set, the latter
    # until after transforms so source shapes propagate through).
    model, list_params, expr_params = create_model(request.model)

    # Setup population
    setup_population(model, request.population)

    # Add age-varying base parameters now that the population is resolved.
    apply_age_varying_parameters(model, list_params)

    # Inject preset-scoped parameter conversions (period→rate, R0→β).
    # Custom models (no preset) opt out: pass {} so nothing is injected.
    preset_def = PRESETS[request.model.preset] if request.model.preset else None
    conversions = preset_def.parameter_conversions if preset_def else {}
    user_scalar_names = {
        k for k, v in (request.model.parameters or {}).items() if not isinstance(v, str)
    }
    converted = resolve_parameter_conversions(model.parameters, user_scalar_names, conversions)
    # User calc-params still win over registry-injected conversions on collision.
    expr_params = {**converted, **expr_params}

    # Apply interventions
    apply_interventions(model, request.interventions)

    # Source-pass transforms first (balcan/scale/override on non-calc names).
    # All downstream stages (transforms, vaccination, run, parameter extraction)
    # use the padded `internal_sim`; the result is trimmed back to the user's
    # original `end_date` before being returned.
    calc_names = set(expr_params)
    apply_parameter_transforms_sources(
        model,
        request.parameter_transforms,
        internal_sim,
        calculated_names=calc_names,
    )

    # Evaluate calculated (expression) parameters now that all source
    # values have their final shapes.
    apply_calculated_parameters(model, expr_params)

    # Calc-pass transforms on top of evaluated calc-params.
    apply_parameter_transforms_calc(
        model,
        request.parameter_transforms,
        internal_sim,
        calculated_names=calc_names,
    )

    # Create initial conditions first so coverage-cap thresholds can be
    # resolved against the t=0 population in apply_vaccinations.
    initial_conditions = create_initial_conditions(
        model,
        request.initial_conditions,
        preset_default=preset_def.default_initial_conditions if preset_def else None,
    )

    # Vaccination flow (source to vaccinated target). Mutates model in place;
    # no-op when the request has no `vaccination` block. Returns the resolved
    # flows (including V-SEIHR's defaulted Susceptible -> Susceptible_vax)
    # so we can echo them in metadata.
    resolved_flows = apply_vaccinations(
        model,
        request.vaccination,
        internal_sim,
        request.model.preset,
        initial_conditions=initial_conditions,
    )

    # Create random number generator from seed if provided
    rng = None
    if internal_sim.seed is not None:
        rng = np.random.default_rng(internal_sim.seed)

    # Run simulations
    results = model.run_simulations(
        start_date=internal_sim.start_date,
        end_date=internal_sim.end_date,
        Nsim=internal_sim.Nsim,
        dt=internal_sim.dt,
        initial_conditions_dict=initial_conditions,
        resample_frequency=internal_sim.resample_frequency,
        rng=rng,
    )

    # Drop the padded trailing day(s) so the response matches the user's
    # requested `end_date`. No-op when `dt >= 1.0` (no padding applied).
    _trim_results_to_end_date(results, request.simulation.end_date)

    # Process results
    results_data = process_results(results, request.output, model)

    # Optionally attach effective per-step parameter arrays for plotting.
    # Build them on the padded grid (so any time-array parameters baked in
    # by transforms broadcast cleanly) and trim back to the user's range.
    if request.output is not None and request.output.include_parameters:
        params = extract_parameter_results(model, internal_sim)
        results_data.parameters = _trim_parameter_results(params, request.simulation.end_date)

    # Build metadata. Surface the resolved vaccination flows so callers can
    # see the V-SEIHR default (Susceptible -> Susceptible_vax) rather than
    # `flows: null`.
    vaccination_metadata = request.vaccination
    if vaccination_metadata is not None and resolved_flows is not None:
        vaccination_metadata = vaccination_metadata.model_copy(update={"flows": resolved_flows})
    metadata = SimulationMetadata(
        model=ModelMetadata(
            preset=request.model.preset,
            compartments=model.compartments,
        ),
        population=_build_population_metadata(request.population, model.population),
        simulation=_build_run_metadata(request),
        interventions=request.interventions,
        parameter_transforms=request.parameter_transforms,
        vaccination=vaccination_metadata,
    )

    return SimulationResponse(
        simulation_id=simulation_id,
        status="completed",
        metadata=metadata,
        results=results_data,
    )
