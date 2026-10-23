"""Post-processing utilities for simulation results.

This module provides functions for transforming epydemix simulation results
into the API response format, including hierarchical data structures,
trajectory extraction, and summary statistics computation.
"""

import numpy as np
import pandas as pd
from epydemix.model.epimodel import EpiModel
from epydemix.model.simulation_results import SimulationResults

from ..api.v1.schemas.simulation import (
    CompartmentResults,
    OutputConfig,
    PeakStatistic,
    SimulationResultsData,
    StatisticQuantiles,
    SummaryResults,
    TrajectoriesResults,
    TrajectoryData,
    TransitionResults,
)
from ..utils.column_utils import parse_column_name

DEFAULT_QUANTILES: list[float] = [0.025, 0.05, 0.25, 0.5, 0.75, 0.95, 0.975]


def build_quantile_hierarchy(
    df: pd.DataFrame,
    known_bases: list[str],
    quantiles_used: list[float],
    filter_bases: list[str] | None,
    filter_age_groups: list[str] | None,
) -> dict[str, dict[str, dict[str, list[float]]]]:
    """Build hierarchical data structure from quantiles dataframe.

    Transforms a flat dataframe with columns like 'Infected_0-4', 'Infected_total'
    into a nested dictionary structure organized by base name, age group, and quantile.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with 'date', 'quantile' columns and data columns.
    known_bases : list of str
        Known base names for column parsing (e.g., compartment or transition names).
    quantiles_used : list of float
        List of quantile values present in the data.
    filter_bases : list of str or None
        If provided, only include these base names in output.
    filter_age_groups : list of str or None
        If provided, only include these age groups in output.

    Returns
    -------
    dict
        Nested dictionary with structure:
        ``{base_name: {age_group: {quantile_str: [values]}}}``.
    """
    cols = [c for c in df.columns if c not in ["date", "quantile"]]

    hierarchical: dict[str, dict[str, dict[str, list[float]]]] = {}

    for col in cols:
        base_name, age_group = parse_column_name(col, known_bases)

        # Apply filters
        if filter_bases is not None and base_name not in filter_bases:
            continue
        if filter_age_groups is not None and age_group not in filter_age_groups:
            continue

        if base_name not in hierarchical:
            hierarchical[base_name] = {}
        if age_group not in hierarchical[base_name]:
            hierarchical[base_name][age_group] = {}

        for q in quantiles_used:
            q_data = df[df["quantile"] == q][col].values.tolist()
            hierarchical[base_name][age_group][str(q)] = q_data

    return hierarchical


def extract_trajectories(
    results: SimulationResults,
    output_config: OutputConfig,
    compartment_names: list[str],
    transition_names: list[str],
) -> TrajectoriesResults:
    """Extract raw trajectory data from simulation results.

    Converts the raw simulation trajectories into a hierarchical structure
    organized by compartment/transition name and age group.

    Parameters
    ----------
    results : SimulationResults
        Simulation results from epydemix.
    output_config : OutputConfig
        Output configuration specifying filters (e.g., age_groups).
    compartment_names : list of str
        List of compartment names from the model.
    transition_names : list of str
        List of transition names (e.g., ['S_to_I', 'I_to_R']).

    Returns
    -------
    TrajectoriesResults
        Trajectory data with hierarchical structure for each simulation run.
    """
    dates = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in results.dates]

    age_groups_filter = output_config.age_groups

    runs = []
    for trajectory in results.trajectories:
        # Build hierarchical compartments: {compartment: {age_group: [values]}}
        compartments: dict[str, dict[str, list[float]]] = {}
        for col_name, values in trajectory.compartments.items():
            base_name, age_group = parse_column_name(col_name, compartment_names)
            if age_groups_filter is not None and age_group not in age_groups_filter:
                continue
            if base_name not in compartments:
                compartments[base_name] = {}
            compartments[base_name][age_group] = values.tolist()

        # Build hierarchical transitions: {transition: {age_group: [values]}}
        transitions: dict[str, dict[str, list[float]]] = {}
        for col_name, values in trajectory.transitions.items():
            base_name, age_group = parse_column_name(col_name, transition_names)
            if age_groups_filter is not None and age_group not in age_groups_filter:
                continue
            if base_name not in transitions:
                transitions[base_name] = {}
            transitions[base_name][age_group] = values.tolist()

        runs.append(TrajectoryData(compartments=compartments, transitions=transitions))

    return TrajectoriesResults(dates=dates, runs=runs)


def _format_date(date_val) -> str | None:
    """Format a date value as YYYY-MM-DD, returning None for NaT."""
    ts = pd.Timestamp(date_val)
    if pd.isna(ts):
        return None
    return ts.strftime("%Y-%m-%d")


def _resolve_age_groups(
    requested: list[str] | None,
    available: list[str],
) -> list[str]:
    """Resolve the age groups to compute summary stats for.

    ``available`` is the canonical list of age-group names (typically
    ``population.Nk_names`` + ``"total"``); we don't infer it by stripping
    keys from the stacked dict because that breaks for V-SEIHR-style models
    where compartment names can have a ``_vax`` suffix that overlaps an
    unrelated compartment's prefix (e.g. ``Susceptible_vax_0-4`` would
    masquerade as age group ``vax_0-4`` under base ``Susceptible``).
    """
    if requested is None:
        return list(available)
    return [g for g in requested if g in available]


def compute_summary(
    results: SimulationResults,
    peak_compartments: list[str],
    total_transitions: list[str],
    age_groups: list[str] | None,
    quantiles: list[float],
    population_age_groups: list[str],
) -> SummaryResults | None:
    """Compute summary statistics from simulation results.

    For each requested compartment or transition, emits per-quantile peak or
    cumulative-total statistics per age group. Peaks additionally include a
    `peak_date` from the median trajectory of that age group.

    Parameters
    ----------
    results : SimulationResults
        Simulation results from epydemix.
    peak_compartments : list of str
        Base compartment names to compute peak statistics for. Empty list
        disables peak computation.
    total_transitions : list of str
        Base transition names (e.g. `S_to_I`) to compute cumulative totals
        for. Empty list disables total computation.
    age_groups : list of str or None
        Age groups to include. `None` means every age group that has data
        (ordered as they appear in the simulation, with `total` last).
    quantiles : list of float
        Quantiles to compute for each statistic (e.g. `[0.025, 0.5, 0.975]`).

    Returns
    -------
    SummaryResults or None
        Summary statistics, or None if neither peaks nor totals were
        computed (for example, both input lists were empty).
    """
    peaks: dict[str, dict[str, PeakStatistic]] = {}
    totals: dict[str, dict[str, StatisticQuantiles]] = {}

    available_age_groups = list(population_age_groups) + ["total"]

    if peak_compartments:
        stacked = results.get_stacked_compartments()
        resolved_groups = _resolve_age_groups(age_groups, available_age_groups)
        for comp_name in peak_compartments:
            peak_by_group: dict[str, PeakStatistic] = {}
            for age_group in resolved_groups:
                key = f"{comp_name}_{age_group}"
                if key not in stacked:
                    continue
                comp_data = stacked[key]  # shape: (Nsim, timesteps)
                peak_per_sim = np.max(comp_data, axis=1)
                quantile_values = {str(q): float(np.quantile(peak_per_sim, q)) for q in quantiles}

                median_traj = np.median(comp_data, axis=0)
                peak_idx = int(np.argmax(median_traj))
                peak_date = None
                if len(results.dates) > peak_idx:
                    peak_date = _format_date(results.dates[peak_idx])

                peak_by_group[age_group] = PeakStatistic(
                    quantiles=quantile_values, peak_date=peak_date
                )
            if peak_by_group:
                peaks[comp_name] = peak_by_group

    if total_transitions:
        trans_stacked = results.get_stacked_transitions()
        resolved_groups = _resolve_age_groups(age_groups, available_age_groups)
        for trans_name in total_transitions:
            total_by_group: dict[str, StatisticQuantiles] = {}
            for age_group in resolved_groups:
                key = f"{trans_name}_{age_group}"
                if key not in trans_stacked:
                    continue
                trans_data = trans_stacked[key]
                total_per_sim = np.sum(trans_data, axis=1)
                quantile_values = {str(q): float(np.quantile(total_per_sim, q)) for q in quantiles}
                total_by_group[age_group] = StatisticQuantiles(quantiles=quantile_values)
            if total_by_group:
                totals[trans_name] = total_by_group

    if not peaks and not totals:
        return None

    return SummaryResults(
        peaks=peaks if peaks else None,
        totals=totals if totals else None,
    )


def process_results(
    results: SimulationResults,
    output_config: OutputConfig | None,
    model: EpiModel,
) -> "SimulationResultsData":
    """Process simulation results into API response format.

    Transforms raw epydemix simulation results into the structured response
    format, including compartment quantiles, transition quantiles, optional
    summary statistics, and optional raw trajectories.

    Parameters
    ----------
    results : SimulationResults
        Simulation results from epydemix.
    output_config : OutputConfig or None
        Output configuration specifying quantiles, filters, and options.
        Uses defaults if None.
    model : EpiModel
        The EpiModel used for the simulation, needed for compartment and
        transition names.

    Returns
    -------
    SimulationResultsData
        Processed results containing compartments, transitions, and
        optionally summary statistics and raw trajectories.
    """
    # Import here to avoid circular imports
    from ..api.v1.schemas.simulation import SimulationResultsData

    if output_config is None:
        output_config = OutputConfig()

    # Get compartment quantiles (None lets epydemix use its default)
    comp_df = results.get_quantiles_compartments(quantiles=output_config.quantiles)
    dates = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in comp_df["date"].unique()]

    # Get the actual quantiles used (from the dataframe)
    quantiles_used = sorted(comp_df["quantile"].unique().tolist())

    # Known compartment names from model
    compartment_names = model.compartments

    # Build hierarchical compartment data
    comp_data = build_quantile_hierarchy(
        comp_df,
        compartment_names,
        quantiles_used,
        output_config.compartments,
        output_config.age_groups,
    )
    compartment_results = CompartmentResults(dates=dates, data=comp_data)

    # Get transition quantiles
    trans_df = results.get_quantiles_transitions(quantiles=output_config.quantiles)

    # Known transition names from model
    transition_names = [f"{t.source}_to_{t.target}" for t in model.transitions_list]

    # Build hierarchical transition data
    trans_data = build_quantile_hierarchy(
        trans_df,
        transition_names,
        quantiles_used,
        output_config.transitions,
        output_config.age_groups,
    )
    transition_results = TransitionResults(dates=dates, data=trans_data)

    # Compute summary statistics. Default to all compartments/transitions when
    # the user did not specify a field; an empty list is an explicit opt-out.
    user_summary = output_config.summary
    resolved_peaks = (
        user_summary.peak_compartments
        if user_summary is not None and user_summary.peak_compartments is not None
        else compartment_names
    )
    resolved_totals = (
        user_summary.total_transitions
        if user_summary is not None and user_summary.total_transitions is not None
        else transition_names
    )
    summary = compute_summary(
        results,
        peak_compartments=resolved_peaks,
        total_transitions=resolved_totals,
        age_groups=output_config.age_groups,
        quantiles=output_config.quantiles or DEFAULT_QUANTILES,
        population_age_groups=[str(name) for name in model.population.Nk_names],
    )

    # Include raw trajectories if requested
    trajectories = None
    if output_config.include_trajectories:
        trajectories = extract_trajectories(
            results, output_config, compartment_names, transition_names
        )

    return SimulationResultsData(
        compartments=compartment_results,
        transitions=transition_results,
        summary=summary,
        trajectories=trajectories,
    )
