"""Unit tests specific to the ``flat_count`` rollout strategy.

Covers the count-based schedule builder, end-to-end delivery against a
minimal X / X_vax model, and the count-based depletion path through the
rate function. Strategy-agnostic rate-fn behavior and helpers live in
``tests/test_vaccination.py``.
"""

import numpy as np
import pytest
from epydemix.model.epimodel import EpiModel
from epydemix.population.population import Population
from epydemix.utils.utils import compute_simulation_dates

from app.utils.vaccination import (
    ResolvedCampaign,
    build_flat_count_schedule,
    make_vaccination_rate_fn,
    register_vaccination_kind,
)


def _minimal_model(initial_X: float = 1_000_000.0) -> tuple[EpiModel, dict]:
    """Two compartments X / X_vax, one age group, no infection dynamics."""
    model = EpiModel(compartments=["X", "X_vax"])
    pop = Population(name="test")
    pop.add_population(Nk=[initial_X], Nk_names=["all"])
    pop.add_contact_matrix(contact_matrix=np.array([[1.0]]), layer_name="all")
    model.set_population(pop)
    return model, {"X": np.array([initial_X]), "X_vax": np.array([0.0])}


def test_schedule_zero_outside_window():
    """`build_flat_count_schedule` puts zeros outside the campaign window."""
    dates = compute_simulation_dates("2025-01-01", "2025-01-31", dt=1.0)
    schedule = build_flat_count_schedule(dates, "2025-01-10", "2025-01-20", 500.0)
    assert schedule.shape == (len(dates),)
    for i, d in enumerate(dates):
        date_str = np.datetime_as_string(d, unit="D")
        if "2025-01-10" <= date_str <= "2025-01-20":
            assert schedule[i] == 500.0, f"in-window step {date_str} should be 500"
        else:
            assert schedule[i] == 0.0, f"out-of-window step {date_str} should be 0"


def test_flat_count_delivers_expected_doses_per_day():
    """Each in-window day delivers approximately `daily_doses * dt` transitions."""
    model, initial = _minimal_model(initial_X=1_000_000.0)
    sim_start, sim_end, dt = "2025-01-01", "2025-02-28", 1.0
    c_start, c_end = "2025-01-10", "2025-01-20"
    daily_doses = 1000.0

    sim_dates = compute_simulation_dates(sim_start, sim_end, dt=dt)
    schedule = build_flat_count_schedule(sim_dates, c_start, c_end, daily_doses)
    campaign = ResolvedCampaign(schedule_at_t=schedule, target_age_indices=np.array([0]))
    rate_fn = make_vaccination_rate_fn([campaign], n_groups=1)
    register_vaccination_kind(model, rate_fn)
    model.add_transition(
        source="X",
        target="X_vax",
        kind="vaccination",
        params={"source": "X", "denominator_sources": ("X",)},
    )

    results = model.run_simulations(
        start_date=sim_start,
        end_date=sim_end,
        Nsim=50,
        dt=dt,
        initial_conditions_dict=initial,
        rng=np.random.default_rng(42),
    )

    per_step = np.stack([traj.transitions["X_to_X_vax_total"] for traj in results.trajectories])
    mean_per_step = per_step.mean(axis=0)

    in_window = (sim_dates >= np.datetime64(c_start)) & (sim_dates <= np.datetime64(c_end))
    # With Nsim=50 and 1M source, per-step SE on the mean is ~4.47; rel=0.03
    # leaves headroom against worst-case empirical drift.
    assert mean_per_step[in_window] == pytest.approx(daily_doses, rel=0.03)
    assert np.all(per_step[:, ~in_window] == 0)


def test_dose_cap_when_source_depleted():
    """When `daily_doses` >> available source, total transitions cap at the source pool."""
    initial_X = 1000.0
    model, initial = _minimal_model(initial_X=initial_X)
    sim_dates = compute_simulation_dates("2025-01-01", "2025-01-31", dt=1.0)
    schedule = build_flat_count_schedule(sim_dates, "2025-01-01", "2025-01-31", 100_000)
    campaign = ResolvedCampaign(schedule_at_t=schedule, target_age_indices=np.array([0]))
    rate_fn = make_vaccination_rate_fn([campaign], n_groups=1)
    register_vaccination_kind(model, rate_fn)
    model.add_transition(
        source="X",
        target="X_vax",
        kind="vaccination",
        params={"source": "X", "denominator_sources": ("X",)},
    )

    results = model.run_simulations(
        start_date="2025-01-01",
        end_date="2025-01-31",
        Nsim=20,
        dt=1.0,
        initial_conditions_dict=initial,
        rng=np.random.default_rng(0),
    )
    totals = np.array([traj.transitions["X_to_X_vax_total"].sum() for traj in results.trajectories])
    # Total vaccinations cannot exceed the finite source pool. One-sided hard
    # invariant.
    assert np.all(totals <= initial_X)
    # With 100k/day on a 31-day window over 1000 individuals, draining is
    # essentially deterministic.
    assert totals.mean() == pytest.approx(initial_X, rel=0.01)


def test_depletion_shoulder_matches_discrete_theory():
    """Per-step transitions match the theoretical value of discrete-time depletion.

    The rate function returns a per-individual rate `r(t) = daily_doses / S(t)`,
    converted by the simulator to a per-step survival-corrected probability:

        p(t) = 1 - exp(-r(t) * dt) = 1 - exp(-c / S(t)),  c = daily_doses * dt
        E[ΔS(t)] = S(t) * p(t) = S(t) * (1 - exp(-c / S(t)))
        S(t+1)   = S(t) - E[ΔS(t)] = S(t) * exp(-c / S(t))
    """
    N = 10_000.0
    daily_doses = 5_000.0
    dt = 1.0
    horizon_days = 8

    model, initial = _minimal_model(initial_X=N)
    sim_dates = compute_simulation_dates("2025-01-01", "2025-01-08", dt=dt)
    schedule = build_flat_count_schedule(sim_dates, "2025-01-01", "2025-01-08", daily_doses)
    campaign = ResolvedCampaign(schedule_at_t=schedule, target_age_indices=np.array([0]))
    rate_fn = make_vaccination_rate_fn([campaign], n_groups=1)
    register_vaccination_kind(model, rate_fn)
    model.add_transition(
        source="X",
        target="X_vax",
        kind="vaccination",
        params={"source": "X", "denominator_sources": ("X",)},
    )

    results = model.run_simulations(
        start_date="2025-01-01",
        end_date="2025-01-08",
        Nsim=300,
        dt=dt,
        initial_conditions_dict=initial,
        rng=np.random.default_rng(3),
    )
    per_step = np.stack([traj.transitions["X_to_X_vax_total"] for traj in results.trajectories])
    mean_per_step = per_step.mean(axis=0)

    c = daily_doses * dt
    s = N
    expected = np.empty(horizon_days, dtype=np.float64)
    for k in range(horizon_days):
        if s <= 0:
            expected[k] = 0.0
            continue
        p = 1.0 - np.exp(-c / s)
        delta = s * p
        expected[k] = delta
        s -= delta

    for k in range(horizon_days):
        if expected[k] < 1:
            continue
        assert mean_per_step[k] == pytest.approx(expected[k], rel=0.05), f"step {k}"
