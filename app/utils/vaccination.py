"""Vaccination custom transition kind and per-strategy schedule builders.

Adds a ``vaccination`` transition kind to an epydemix model. The kind's
rate function reads the current populations of every source compartment
competing for doses (``denominator_sources`` from the transition params)
and produces a per-age-group rate. Two campaign modes are supported per
campaign:

- **Count-based** (``rate_based=False``, e.g. ``flat_count``): the
  schedule holds a per-day dose count; the rate is
  ``doses / eligible_pool``, so the binomial draw delivers the configured
  count split across age groups proportional to the live source pool.
- **Rate-based** (``rate_based=True``, e.g. ``fixed_rate``): the schedule
  holds a per-day hazard rate; the rate is applied directly with no
  denominator, matching a spontaneous transition at that rate.

Each rollout strategy reduces to producing a length-``T`` ``schedule_at_t``
array plus the ``rate_based`` flag; the rate function consumes both modes.

Campaigns can carry an optional coverage cap (``coverage_threshold`` plus
``vax_compartment_indices``). When the current occupancy of the listed
vaccinated compartments, restricted to ``target_age_indices``, reaches the
threshold, that campaign stops contributing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from epydemix.model.epimodel import EpiModel


@dataclass(frozen=True)
class ResolvedCampaign:
    """A single campaign reduced to a per-step schedule and a target age subset.

    Attributes
    ----------
    schedule_at_t : np.ndarray
        Shape ``(T,)``. Per-step value driving the rate. For count-based
        campaigns this is a dose count; for rate-based campaigns this is a
        hazard rate. Zero outside the campaign window.
    target_age_indices : np.ndarray
        Shape ``(k,)``, ``int``. Indices into ``population.Nk``.
    rate_based : bool
        ``True`` if ``schedule_at_t`` holds a hazard rate (applied directly);
        ``False`` if it holds a dose count (divided by the eligible pool).
    coverage_threshold : float or None
        Absolute coverage threshold (``fraction * initial_population``).
        ``None`` means no cap.
    vax_compartment_indices : np.ndarray or None
        Indices of "vaccinated" compartments whose current occupancy is
        summed against ``coverage_threshold``. ``None`` means no cap.
    """

    schedule_at_t: np.ndarray
    target_age_indices: np.ndarray
    rate_based: bool = False
    coverage_threshold: float | None = None
    vax_compartment_indices: np.ndarray | None = None


def make_vaccination_rate_fn(
    campaigns: list[ResolvedCampaign],
    n_groups: int,
) -> Callable:
    """Build the rate function for the ``vaccination`` transition kind.

    The returned function is closed over the precomputed schedules. Per
    step, for each active campaign:

    - if a coverage cap is configured, sum current occupancy of
      ``vax_compartment_indices`` across ``target_age_indices`` and skip
      the campaign once at or above ``coverage_threshold``;
    - if ``rate_based``, add the schedule value directly to the rate;
    - otherwise (count-based), divide the schedule value by the live
      eligible-pool sum and add.

    The eligible-pool slices are materialized lazily — only when a
    count-based campaign is active in that step.
    """

    def rate_fn(params, data):
        t = data["t"]
        denom_sources = params["denominator_sources"]
        pop = data["pop"]
        comp_indices = data["comp_indices"]
        rate = np.zeros(n_groups, dtype=np.float64)
        pops: list[np.ndarray] | None = None
        for camp in campaigns:
            # Vaccination schedule at time t. Count or rate depending on campaign type. Zero if outside the campaign window.
            val = camp.schedule_at_t[t]
            if val <= 0:
                continue
            tgt = camp.target_age_indices

            if camp.coverage_threshold is not None and camp.vax_compartment_indices is not None:
                # Sum eligible vaccinated population for coverage cap
                vax_sum = float(sum(pop[i][tgt].sum() for i in camp.vax_compartment_indices))
                if vax_sum >= camp.coverage_threshold:
                    continue  # Skip the campaign if the coverage threshold has been reached
            if camp.rate_based:
                # Directly apply the hazard rate
                rate[tgt] += val
            else:
                if pops is None:
                    pops = [pop[comp_indices[name]] for name in denom_sources]
                # Sum eligible pool across all source compartments
                s_sum = float(sum(p[tgt].sum() for p in pops))
                # Calculate effective rate from the dose count and eligible pool
                if s_sum > 0:
                    rate[tgt] += val / s_sum
        return rate

    return rate_fn


def register_vaccination_kind(model: EpiModel, rate_fn: Callable) -> None:
    """Register ``vaccination`` on the model.

    Safe to call multiple times: the latest registration wins for a given
    model. Each request constructs a fresh model, so cross-request leakage
    is impossible.
    """
    model.register_transition_kind("vaccination", rate_fn)


def build_flat_count_schedule(
    sim_dates: np.ndarray,
    c_start: str,
    c_end: str,
    daily_doses: float,
) -> np.ndarray:
    """Return a length-``T`` schedule for a constant ``daily_doses`` strategy.

    Active inside ``[c_start, c_end]`` (inclusive on both ends, aligned to the
    daily grid), zero outside. The per-day count is not scaled by ``dt``: the
    rate function scales by ``dt`` when computing per-step transitions, so
    callers should not pre-scale here.

    Parameters
    ----------
    sim_dates : np.ndarray
        The simulation date grid from ``compute_simulation_dates``.
    c_start, c_end : str
        Campaign window dates (``YYYY-MM-DD``). Inclusive.
    daily_doses : float
        Constant per-day dose count during the window. Must be ``> 0``;
        upstream schema validation enforces this.
    """
    date_ts = pd.to_datetime([np.datetime_as_string(d, unit="D") for d in sim_dates])
    active = (date_ts >= pd.Timestamp(c_start)) & (date_ts <= pd.Timestamp(c_end))
    return np.where(np.asarray(active), float(daily_doses), 0.0)


def build_fixed_rate_schedule(
    sim_dates: np.ndarray,
    c_start: str,
    c_end: str,
    rate: float,
) -> np.ndarray:
    """Return a length-``T`` schedule for a constant per-day hazard ``rate``.

    Active inside ``[c_start, c_end]`` (inclusive on both ends, aligned to
    the daily grid), zero outside. The rate function applies the value
    directly (no division by an eligible pool), so within the window each
    source individual sees a per-day hazard of ``rate`` of being vaccinated.

    Parameters
    ----------
    sim_dates : np.ndarray
        The simulation date grid from ``compute_simulation_dates``.
    c_start, c_end : str
        Campaign window dates (``YYYY-MM-DD``). Inclusive.
    rate : float
        Per-day hazard rate. Must be ``> 0``; upstream schema enforces this.
    """
    date_ts = pd.to_datetime([np.datetime_as_string(d, unit="D") for d in sim_dates])
    active = (date_ts >= pd.Timestamp(c_start)) & (date_ts <= pd.Timestamp(c_end))
    return np.where(np.asarray(active), float(rate), 0.0)
