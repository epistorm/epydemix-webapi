"""Apply a request-level vaccination block to an epydemix model.

Validates the config, resolves the campaign flows (preset defaults vs. user
overrides), pre-computes one schedule per campaign (count-based for
``flat_count``, rate-based for ``fixed_rate``), resolves any coverage caps,
registers the ``vaccination`` transition kind, and adds one transition per
flow that has a non-null target. The simulator then drives doses during
each step according to the resolved schedules.

Mutates ``model`` in place; no-op when the request supplies no
``vaccination`` block or an empty campaign list.
"""

from __future__ import annotations

import numpy as np
from epydemix.model.epimodel import EpiModel
from epydemix.utils.utils import compute_simulation_dates

from ..api.v1.schemas.simulation import (
    CompartmentFlow,
    FixedRateRollout,
    FlatCountRollout,
    SimulationConfig,
    VaccinationCampaignConfig,
    VaccinationConfig,
)
from ..utils.vaccination import (
    ResolvedCampaign,
    build_fixed_rate_schedule,
    build_flat_count_schedule,
    make_vaccination_rate_fn,
    register_vaccination_kind,
)

_VAX_DEFAULT_FLOWS: tuple[CompartmentFlow, ...] = (
    CompartmentFlow(source="Susceptible", target="Susceptible_vax"),
)

_PRESETS_WITH_DEFAULT_FLOWS: frozenset[str] = frozenset({"V-SEIHR", "V-SEIR"})


def apply_vaccinations(
    model: EpiModel,
    config: VaccinationConfig | None,
    simulation: SimulationConfig,
    preset: str | None,
    initial_conditions: dict[str, np.ndarray] | None = None,
) -> list[CompartmentFlow] | None:
    """Wire the vaccination flow into ``model``.

    Must be called after ``setup_population`` so the age-group names and the
    population vector are available. Order vs. calculated parameters and
    parameter transforms doesn't matter: vaccination uses a custom transition
    kind that reads the source population at each step, not a regular
    parameter.

    ``initial_conditions`` (the dict returned by ``create_initial_conditions``)
    is required only when any campaign carries a ``coverage`` cap, because the
    cap threshold is computed against the t=0 population in the target age
    groups. Pass ``None`` if no campaign uses coverage.

    Returns the resolved flows (with vaccination-preset defaults filled in)
    so callers can surface them in response metadata. Returns ``None`` when
    there is no vaccination block to apply.

    Raises ``ValueError`` (forwarded as 422) on any validation problem:

      - empty ``campaigns`` list when the block is present;
      - missing ``flows`` on a model without a vaccination preset;
      - any flow's ``source`` or non-null ``target`` not in ``model.compartments``;
      - ``target_age_groups`` referencing an unknown age-group label;
      - ``coverage.compartments`` referencing an unknown compartment or one
        that is also a ``source`` in the same campaign's flows;
      - any campaign carrying ``coverage`` while ``initial_conditions`` is
        ``None`` (cannot resolve the threshold denominator).
    """
    if config is None or not config.campaigns:
        if config is not None and not config.campaigns:
            raise ValueError("'vaccination.campaigns' must contain at least one entry")
        return None

    compartments = list(model.compartments)
    flows = _resolve_flows(config, preset, compartments)
    flow_sources = {flow.source for flow in flows}
    denom_sources = tuple(flow.source for flow in flows)
    flows_with_target = [flow for flow in flows if flow.target is not None]

    age_names = [str(name) for name in model.population.Nk_names]
    n_groups = model.population.num_groups
    dates = compute_simulation_dates(simulation.start_date, simulation.end_date, dt=simulation.dt)

    resolved: list[ResolvedCampaign] = []
    for i, camp in enumerate(config.campaigns):
        age_idx = _resolve_age_indices(camp.target_age_groups, age_names)
        schedule, rate_based = _build_schedule(
            camp.rollout, dates, camp.start_date, camp.end_date
        )
        threshold, vax_idx = _resolve_coverage(
            camp, i, compartments, flow_sources, age_idx, initial_conditions
        )
        resolved.append(
            ResolvedCampaign(
                schedule_at_t=schedule,
                target_age_indices=age_idx,
                rate_based=rate_based,
                coverage_threshold=threshold,
                vax_compartment_indices=vax_idx,
            )
        )

    rate_fn = make_vaccination_rate_fn(resolved, n_groups)
    register_vaccination_kind(model, rate_fn)
    for flow in flows_with_target:
        assert flow.target is not None  # narrowed by the filter above
        model.add_transition(
            source=flow.source,
            target=flow.target,
            kind="vaccination",
            params={"source": flow.source, "denominator_sources": denom_sources},
        )

    return flows


def _resolve_flows(
    config: VaccinationConfig,
    preset: str | None,
    compartments: list[str],
) -> list[CompartmentFlow]:
    """Pick the flows for this block, defaulting for vaccination presets.

    - Vaccination presets (see ``_PRESETS_WITH_DEFAULT_FLOWS``): default to
      ``[{Susceptible -> Susceptible_vax}]`` when ``flows`` is omitted. The
      user may override (e.g. to add a dose sink or a second source/target
      pair on a derived model).
    - Other presets / custom models: ``flows`` must be supplied.
    - Every ``source`` and non-null ``target`` must exist in
      ``model.compartments``.
    """
    if config.flows is not None:
        flows = list(config.flows)
    elif preset in _PRESETS_WITH_DEFAULT_FLOWS:
        flows = list(_VAX_DEFAULT_FLOWS)
    else:
        raise ValueError("'vaccination.flows' is required for models without a vaccination preset")

    for i, flow in enumerate(flows):
        if flow.source not in compartments:
            raise ValueError(
                f"'vaccination.flows[{i}].source' = {flow.source!r} is not in "
                f"model.compartments; available: {compartments}"
            )
        if flow.target is not None and flow.target not in compartments:
            raise ValueError(
                f"'vaccination.flows[{i}].target' = {flow.target!r} is not in "
                f"model.compartments; available: {compartments}"
            )
    return flows


def _resolve_age_indices(
    target_age_groups: list[str] | None,
    age_names: list[str],
) -> np.ndarray:
    """Map requested labels to integer indices into ``population.Nk``.

    ``None`` means "all groups"; returns ``[0, 1, ..., N-1]`` in that case.
    Raises ``ValueError`` if any requested label is unknown.
    """
    if target_age_groups is None:
        return np.arange(len(age_names), dtype=np.int64)
    label_to_idx = {name: i for i, name in enumerate(age_names)}
    unknown = [g for g in target_age_groups if g not in label_to_idx]
    if unknown:
        raise ValueError(
            f"'vaccination.target_age_groups' contains unknown label(s) {unknown}; "
            f"valid age groups: {age_names}"
        )
    return np.asarray([label_to_idx[g] for g in target_age_groups], dtype=np.int64)


def _build_schedule(
    rollout,
    dates: np.ndarray,
    c_start: str,
    c_end: str,
) -> tuple[np.ndarray, bool]:
    """Dispatch on the rollout discriminator.

    Returns ``(schedule, rate_based)``. ``rate_based`` is ``True`` when the
    schedule holds a hazard rate to apply directly; ``False`` when it holds
    a dose count to divide by the eligible pool.
    """
    if isinstance(rollout, FlatCountRollout):
        schedule = build_flat_count_schedule(dates, c_start, c_end, rollout.daily_doses)
        return schedule, False
    if isinstance(rollout, FixedRateRollout):
        schedule = build_fixed_rate_schedule(dates, c_start, c_end, rollout.rate)
        return schedule, True
    raise TypeError(f"Unknown rollout type: {type(rollout).__name__}")


def _resolve_coverage(
    camp: VaccinationCampaignConfig,
    camp_index: int,
    compartments: list[str],
    flow_sources: set[str],
    target_age_indices: np.ndarray,
    initial_conditions: dict[str, np.ndarray] | None,
) -> tuple[float | None, np.ndarray | None]:
    """Resolve the coverage cap for one campaign.

    Returns ``(threshold, vax_compartment_indices)`` when a cap is
    configured, or ``(None, None)`` otherwise. Validates that every name in
    ``coverage.compartments`` exists in ``model.compartments`` and is not a
    source of any flow in the same campaign. Computes the threshold as
    ``fraction * sum_over_all_compartments(initial[c][target_age_indices])``.
    """

    # If coverage is not configured, return (no threshold, no compartments to sum)
    if camp.coverage is None:
        return None, None

    if initial_conditions is None:
        raise ValueError(
            f"'vaccination.campaigns[{camp_index}].coverage' is set but no "
            "initial conditions are available; provide 'initial_conditions' "
            "in the request (or use a preset whose default supplies them)."
        )

    comp_to_idx = {name: i for i, name in enumerate(compartments)}
    unknown = [c for c in camp.coverage.compartments if c not in comp_to_idx]
    if unknown:
        raise ValueError(
            f"'vaccination.campaigns[{camp_index}].coverage.compartments' "
            f"contains unknown compartment(s) {unknown}; available: {compartments}"
        )

    overlap = [c for c in camp.coverage.compartments if c in flow_sources]
    if overlap:
        raise ValueError(
            f"'vaccination.campaigns[{camp_index}].coverage.compartments' "
            f"overlaps with flow sources {overlap}; including a source "
            "compartment makes the cap fire before any doses are delivered."
        )

    # Calculate absolute threshold
    initial_population = float(
        sum(arr[target_age_indices].sum() for arr in initial_conditions.values())
    )
    threshold = camp.coverage.fraction * initial_population

    # Index of the vaccinated compartments to sum for coverage tracking
    vax_idx = np.asarray([comp_to_idx[c] for c in camp.coverage.compartments], dtype=np.int64)

    return threshold, vax_idx
