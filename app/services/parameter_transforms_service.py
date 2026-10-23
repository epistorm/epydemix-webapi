"""Parameter-transform application passes.

This is the orchestration layer that walks a request's
``parameter_transforms`` list and writes the resulting arrays back into
``model.parameters``. The math (transform array construction, masking, time
and age broadcasting) lives in ``app.utils.parameter_transforms``; this
module just sequences the source-pass (transforms on user/preset parameters)
and the calc-pass (transforms on calculated/expression parameters).
"""

from __future__ import annotations

import numpy as np
from epydemix.model.epimodel import EpiModel
from epydemix.utils.utils import compute_simulation_dates

from ..api.v1.schemas.simulation import ParameterTransformConfig, SimulationConfig
from ..utils.parameter_transforms import (
    apply_transform_to_parameter,
    broadcast_to_time_and_age,
    compute_transform_array,
    window_mask_for_dates,
)


def _apply_transforms_to_pass(
    model: EpiModel,
    transforms: list[ParameterTransformConfig],
    simulation_config: SimulationConfig,
) -> None:
    """Apply a list of transforms (already filtered to one pass) in place.

    Used by both the source-pass and the calc-pass. Multiplicative transforms
    (``balcan`` / ``scale``) compose in user-supplied order; ``override``
    transforms are applied last so they always win for their window. Each
    transform writes back to ``model.parameters`` via ``add_parameter``.

    Assumes every ``target_parameter`` is already validated to exist in
    ``model.parameters``.
    """
    if not transforms:
        return

    multiplicative = [t for t in transforms if t.method in ("balcan", "scale")]
    overrides = [t for t in transforms if t.method == "override"]

    # Multiplicative transforms compose in user-supplied order.
    # apply_transform_to_parameter always returns a fresh array, so writing
    # new_value back via add_parameter does not alias the previous value.
    for transform in multiplicative:
        existing = model.get_parameter(transform.target_parameter)
        transform_array = compute_transform_array(
            transform,
            simulation_config.start_date,
            simulation_config.end_date,
            simulation_config.dt,
        )
        new_value = apply_transform_to_parameter(existing, transform_array)
        model.add_parameter(parameter_name=transform.target_parameter, value=new_value)

    if not overrides:
        return

    # Overrides write into model.parameters as (T, N) arrays so calculated
    # parameters that reference the target pick up the override automatically
    # (the same way balcan/scale propagate through expressions).
    dates = compute_simulation_dates(
        simulation_config.start_date,
        simulation_config.end_date,
        dt=simulation_config.dt,
    )
    T = len(dates)
    n_groups = model.population.num_groups

    for transform in overrides:
        if isinstance(transform.value, list):
            if len(transform.value) != n_groups:
                raise ValueError(
                    f"parameter_transforms[*].value for '{transform.target_parameter}' has length "
                    f"{len(transform.value)} but population has {n_groups} age groups"
                )
            window_value: np.ndarray | float = np.asarray(transform.value, dtype=np.float64)
        else:
            window_value = float(transform.value)

        existing = model.get_parameter(transform.target_parameter)
        arr = broadcast_to_time_and_age(existing, T, n_groups)
        mask = window_mask_for_dates(transform.start_date, transform.end_date, dates)
        # Scalar broadcasts to (N,); 1D length-N broadcasts across the window's time slice.
        arr[mask, :] = window_value
        model.add_parameter(parameter_name=transform.target_parameter, value=arr)


def apply_parameter_transforms_sources(
    model: EpiModel,
    transforms: list[ParameterTransformConfig] | None,
    simulation_config: SimulationConfig,
    calculated_names: set[str] | None = None,
) -> None:
    """Apply transforms targeting **source** (non-calc-param) parameters.

    Validates target-parameter names against ``model.parameters`` (a typo
    surfaces as a clean error). Skips any transform whose target is a
    calculated parameter; those are deferred to
    ``apply_parameter_transforms_calc`` so they see post-eval values.
    """
    if not transforms:
        return

    calc_names = calculated_names or set()
    pending: list[ParameterTransformConfig] = []
    for transform in transforms:
        if transform.target_parameter in calc_names:
            continue  # deferred to the calc-pass
        if transform.target_parameter not in model.parameters:
            raise ValueError(
                f"parameter_transforms[*].target_parameter '{transform.target_parameter}' is not defined in model.parameters"
            )
        pending.append(transform)

    _apply_transforms_to_pass(model, pending, simulation_config)


def apply_parameter_transforms_calc(
    model: EpiModel,
    transforms: list[ParameterTransformConfig] | None,
    simulation_config: SimulationConfig,
    calculated_names: set[str] | None = None,
) -> None:
    """Apply transforms targeting **calculated** parameters.

    Runs after ``apply_calculated_parameters`` so each calc-param has its
    evaluated array stored on the model. Multiplicative transforms layer on
    top of the evaluated value; overrides replace it within the window. A
    transform on a source still propagates through any expression that
    references it via ``apply_calculated_parameters``; this pass enables an
    *additional* transform on the calc-param itself (e.g. a flat scale on
    ``transmission_rate_vax`` while ``balcan`` modulates ``transmission_rate``).
    """
    if not transforms:
        return

    calc_names = calculated_names or set()
    calc_targeting = [t for t in transforms if t.target_parameter in calc_names]
    if not calc_targeting:
        return

    for transform in calc_targeting:
        if transform.target_parameter not in model.parameters:
            raise ValueError(
                f"parameter_transforms[*].target_parameter '{transform.target_parameter}' is a calculated "
                f"parameter that was not evaluated; check the `parameters` block for the matching expression."
            )

    _apply_transforms_to_pass(model, calc_targeting, simulation_config)
