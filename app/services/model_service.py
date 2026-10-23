"""Model construction and state-mutation helpers.

This module owns everything that builds or mutates an ``EpiModel``'s
parameters, transitions, initial conditions, and interventions, *before*
``run_simulation`` hands it off to epydemix. Parameter-transform passes live
in ``parameter_transforms_service`` and population loading lives in
``population_service``; this module is the rest of the pre-run pipeline.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
from epydemix.model.epimodel import EpiModel
from epydemix.utils.utils import compute_simulation_dates

from ..api.v1.schemas.simulation import (
    InitialConditionsConfig,
    InterventionConfig,
    ModelConfig,
    ParameterResults,
    SimulationConfig,
)
from ..presets import PRESETS
from ..utils.calculated_parameters import compute_reserved_params, evaluate_expressions
from ..utils.parameter_transforms import broadcast_to_time_and_age


def create_model(
    config: ModelConfig,
) -> tuple[EpiModel, dict[str, list[float]], dict[str, str]]:
    """Create an EpiModel from configuration.

    Splits parameters into three groups by value type:

    - Scalars (``float`` / ``int``) are wired in immediately. For presets, the
      preset builder seeds defaults and applies user scalars on top; for
      custom models, scalars are wired straight into ``EpiModel`` at
      construction.
    - List values (age-varying) are returned for application after
      ``setup_population`` has run, since epydemix needs
      ``population.num_groups`` for shape checks.
    - String values are expressions over other parameters and are returned
      for evaluation after ``parameter_transforms`` so transformed source
      shapes propagate through.

    For presets, any preset-specific calculated parameters (e.g. V-SEIHR's
    VE twins) are merged into ``expr_params``; user-supplied calc-params win
    on collision.
    """
    raw = config.parameters or {}
    scalar_params: dict[str, float] = {
        k: float(v)
        for k, v in raw.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    list_params: dict[str, list[float]] = {k: v for k, v in raw.items() if isinstance(v, list)}
    expr_params: dict[str, str] = {k: v for k, v in raw.items() if isinstance(v, str)}

    if config.preset:
        preset_def = PRESETS[config.preset]
        # Thread list-valued preset defaults into the age-varying pipeline.
        # Any user override (scalar or list) for the same key wins.
        preset_list_defaults = {
            k: v
            for k, v in preset_def.default_parameters.items()
            if isinstance(v, list) and k not in raw
        }
        list_params = {**preset_list_defaults, **list_params}
        model, preset_calc_params = preset_def.build_model(scalar_params)
        # User calc-params win on collision (sensitivity scans, custom calibration).
        expr_params = {**preset_calc_params, **expr_params}
        return model, list_params, expr_params

    model = EpiModel(compartments=config.compartments, parameters=scalar_params)

    if config.transitions:
        for trans in config.transitions:
            params = trans.params
            # Spontaneous: single parameter name; mediated: tuple of (rate, compartment)
            if len(params) == 1:
                params = params[0]
            else:
                params = tuple(params)
            model.add_transition(
                source=trans.source,
                target=trans.target,
                kind=trans.kind,
                params=params,
            )

    return model, list_params, expr_params


def apply_age_varying_parameters(
    model: EpiModel,
    list_params: dict[str, list[float]],
) -> None:
    """Add length-N age-varying parameters after the population is set.

    Validates list length against `model.population.num_groups` and stores a
    fresh `np.array` so the model does not retain a reference to the
    request-supplied list. Mutates `model` in place.
    """
    if not list_params:
        return

    n_groups = model.population.num_groups
    for name, value in list_params.items():
        if len(value) != n_groups:
            raise ValueError(
                f"Parameter '{name}' has length {len(value)} but population has {n_groups} age groups"
            )
        # Epydemix represents age-varying parameters as 2D arrays of shape (1, N).
        # A 1D shape (N,) is interpreted as a (too-short) time series.
        model.add_parameter(parameter_name=name, value=np.array(value).reshape(1, n_groups))


def create_initial_conditions(
    model: EpiModel,
    config: InitialConditionsConfig | None,
    preset_default: Callable[[EpiModel], dict[str, np.ndarray]] | None = None,
) -> dict[str, np.ndarray] | None:
    """Create initial conditions dictionary from configuration.

    Builds initial conditions either from absolute counts per compartment
    or from percentages of the total population. If no config is supplied
    and the preset provides its own ``default_initial_conditions`` callable,
    that is used; otherwise we fall through to epydemix's built-in default.

    Parameters
    ----------
    model : EpiModel
        EpiModel with population already set, needed for population counts.
    config : InitialConditionsConfig or None
        Initial conditions configuration.
    preset_default : callable, optional
        Preset-supplied default initial conditions builder. Invoked only when
        ``config`` is None.

    Returns
    -------
    dict of {str: np.ndarray} or None
        Dictionary mapping compartment names to arrays of counts per age group,
        or None to use epydemix default initial conditions.
    """
    if config is None:
        if preset_default is not None:
            return preset_default(model)
        return None

    if config.method == "absolute" and config.compartments:
        # Check initial count lengths.
        n_groups = len(model.population.Nk)
        for name, counts in config.compartments.items():
            if len(counts) != n_groups:
                raise ValueError(
                    f"initial_conditions.compartments['{name}'] has {len(counts)} value(s) "
                    f"but the population has {n_groups} age groups"
                )
        return {k: np.array(v) for k, v in config.compartments.items()}

    if config.method == "percentage" and config.initial_percentages:
        # Build initial conditions from percentages
        # Get population per age group
        pop_per_group = np.array(model.population.Nk)

        initial_conditions: dict[str, np.ndarray] = {}

        # Calculate counts for each specified compartment
        remaining_pop = pop_per_group.copy().astype(float)
        for comp_name, percentage in config.initial_percentages.items():
            # Distribute percentage proportionally across age groups
            comp_count = pop_per_group * (percentage / 100.0)
            initial_conditions[comp_name] = comp_count
            remaining_pop -= comp_count

        # Assign remaining population to first compartment (typically Susceptible)
        first_compartment = model.compartments[0]
        if first_compartment not in initial_conditions:
            initial_conditions[first_compartment] = remaining_pop
        else:
            initial_conditions[first_compartment] += remaining_pop

        return initial_conditions

    return None


def apply_interventions(model: EpiModel, interventions: list[InterventionConfig] | None) -> None:
    """Apply contact reduction interventions to the model.

    Adds interventions that modify contact rates in specific layers
    during specified time periods.

    Parameters
    ----------
    model : EpiModel
        EpiModel to configure with interventions.
    interventions : list of InterventionConfig or None
        List of intervention configurations. If None or empty, no
        interventions are applied.
    """
    if not interventions:
        return

    for intervention in interventions:
        model.add_intervention(
            layer_name=intervention.layer_name,
            start_date=intervention.start_date,
            end_date=intervention.end_date,
            reduction_factor=intervention.reduction_factor,
            name=intervention.name or "",
        )


def apply_calculated_parameters(
    model: EpiModel,
    expr_params: dict[str, str],
) -> None:
    """Evaluate expression-valued parameters and add the results to the model.

    Runs after scalars, age-varying values, and `parameter_transforms`, so
    each expression sees the post-transform shapes of its sources and numpy
    broadcasting carries time- and age-variation through naturally.

    Reserved names (e.g. ``CONTACT_MATRIX_EIGENVALUE_ALL``) are computed from
    the model state and injected into the eval namespace alongside
    ``model.parameters``. They are NOT stored on the model and so do not
    appear in ``results.parameters``.

    Mutates `model` in place. Raises `ValueError` (forwarded as 422) on
    syntax errors, disallowed AST nodes, undefined name references, or
    circular dependencies among expressions.
    """
    if not expr_params:
        return

    namespace: dict[str, object] = dict(model.parameters)
    namespace.update(compute_reserved_params(model))
    results = evaluate_expressions(expr_params, namespace)
    for name, value in results.items():
        model.add_parameter(parameter_name=name, value=value)


def extract_parameter_results(
    model: EpiModel, simulation_config: SimulationConfig
) -> ParameterResults:
    """Build the per-step effective parameter arrays for the response.

    Walks the same date grid the simulator uses (``compute_simulation_dates``)
    and broadcasts each parameter in ``model.parameters`` to a ``(T, N)``
    array. Transforms (including overrides) have already been baked into
    ``model.parameters`` upstream, so the returned arrays match exactly what
    the simulator runs with.
    """
    dates = compute_simulation_dates(
        simulation_config.start_date,
        simulation_config.end_date,
        dt=simulation_config.dt,
    )
    T = len(dates)
    age_groups = [str(name) for name in model.population.Nk_names]
    N = len(age_groups)

    date_strs = [str(np.datetime_as_string(d, unit="D")) for d in dates]

    data: dict[str, dict[str, list[float]]] = {}
    for name, value in model.parameters.items():
        try:
            arr = broadcast_to_time_and_age(value, T, N)
        except ValueError:
            # Unknown shape (e.g. wrapped object array). Skip rather than fail.
            continue
        data[name] = {age_groups[i]: arr[:, i].tolist() for i in range(N)}

    return ParameterResults(dates=date_strs, data=data)
