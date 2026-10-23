"""Unit tests for strategy-agnostic vaccination machinery.

Covers the rate function's shared behavior (idle steps, empty source pool,
multi-source denominators), multi-group / multi-campaign composition, and
the coverage cap (which composes with both rollout strategies). Strategy-
specific tests live in ``test_vaccination_flat_count.py`` and
``test_vaccination_fixed_rate.py``.
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


def test_rate_fn_inactive_campaign_returns_zero():
    """When the schedule is zero at step `t`, the rate function returns all zeros."""
    schedule = np.zeros(10, dtype=float)  # Zero doses across the window
    campaign = ResolvedCampaign(schedule_at_t=schedule, target_age_indices=np.array([0]))
    rate_fn = make_vaccination_rate_fn([campaign], n_groups=1)
    rate = rate_fn(
        {"source": "X", "denominator_sources": ("X",)},
        {"t": 0, "pop": np.array([[100.0], [0.0]]), "comp_indices": {"X": 0, "X_vax": 1}},
    )
    assert rate == pytest.approx(0.0, abs=1e-12)


def test_rate_fn_with_empty_source_returns_zero():
    """When the source compartment is empty, the rate function returns zero (no NaN)."""
    schedule = np.array([100.0, 100.0])
    campaign = ResolvedCampaign(schedule_at_t=schedule, target_age_indices=np.array([0]))
    rate_fn = make_vaccination_rate_fn([campaign], n_groups=1)
    # Population is zero in the source compartment, which could lead to division by zero if not handled properly.
    rate = rate_fn(
        {"source": "X", "denominator_sources": ("X",)},
        {"t": 0, "pop": np.array([[0.0], [0.0]]), "comp_indices": {"X": 0, "X_vax": 1}},
    )
    assert np.all(np.isfinite(rate))
    assert rate == pytest.approx(0.0, abs=1e-12)


def test_rate_fn_multi_source_denominator():
    """Multi-source `denominator_sources` reproduces the upstream `D/(S+R)` rule.

    With S=200, R=300, daily_doses=50, the per-individual rate should be
    50/(200+300) = 0.1; the same value applies to every individual in any
    of the listed source compartments, even though the binomial draw is only
    against the per-transition source.
    """
    schedule = np.array([50.0])
    campaign = ResolvedCampaign(schedule_at_t=schedule, target_age_indices=np.array([0]))
    rate_fn = make_vaccination_rate_fn([campaign], n_groups=1)
    rate = rate_fn(
        {"source": "S", "denominator_sources": ("S", "R")},
        {
            "t": 0,
            "pop": np.array([[200.0], [300.0], [0.0]]),
            "comp_indices": {"S": 0, "R": 1, "S_vax": 2},
        },
    )
    assert rate[0] == pytest.approx(50.0 / (200.0 + 300.0))


def _two_group_model(nk: list[float]) -> tuple[EpiModel, dict]:
    """Two compartments X / X_vax, two age groups, no infection dynamics."""
    model = EpiModel(compartments=["X", "X_vax"])
    pop = Population(name="two_group")
    pop.add_population(Nk=nk, Nk_names=["A", "B"])
    pop.add_contact_matrix(
        contact_matrix=np.array([[1.0, 1.0], [1.0, 1.0]]),
        layer_name="all",
    )
    model.set_population(pop)
    return model, {
        "X": np.array(nk, dtype=float),
        "X_vax": np.zeros(len(nk), dtype=float),
    }


def _wire_vaccination(
    model: EpiModel,
    schedules_and_targets: list[tuple[np.ndarray, np.ndarray]],
    n_groups: int,
) -> None:
    campaigns = [
        ResolvedCampaign(schedule_at_t=schedule, target_age_indices=targets)
        for schedule, targets in schedules_and_targets
    ]
    rate_fn = make_vaccination_rate_fn(campaigns, n_groups=n_groups)
    register_vaccination_kind(model, rate_fn)
    model.add_transition(
        source="X",
        target="X_vax",
        kind="vaccination",
        params={"source": "X", "denominator_sources": ("X",)},
    )


def test_two_groups_proportional_split():
    """Doses split across target groups proportional to current S_i(t).

    With a 60/40 source split and a large source pool relative to total doses
    (so depletion is negligible during the window), per-group cumulative
    transitions should land on a 60/40 ratio within stochastic noise.
    """
    nk = [60_000.0, 40_000.0]
    model, initial = _two_group_model(nk)
    sim_dates = compute_simulation_dates("2025-01-01", "2025-01-31", dt=1.0)
    schedule = build_flat_count_schedule(sim_dates, "2025-01-05", "2025-01-15", 100.0)
    _wire_vaccination(model, [(schedule, np.array([0, 1]))], n_groups=2)

    results = model.run_simulations(
        start_date="2025-01-01",
        end_date="2025-01-31",
        Nsim=200,
        dt=1.0,
        initial_conditions_dict=initial,
        rng=np.random.default_rng(0),
    )

    # Calculate cumulative transitions per group across the window.
    per_group_totals = {
        "A": np.array([traj.transitions["X_to_X_vax_A"].sum() for traj in results.trajectories]),
        "B": np.array([traj.transitions["X_to_X_vax_B"].sum() for traj in results.trajectories]),
    }
    total_mean = per_group_totals["A"].mean() + per_group_totals["B"].mean()

    # Group A should receive ~60% of the doses, Group B ~40%, with some noise.
    a_share = per_group_totals["A"].mean() / total_mean
    assert a_share == pytest.approx(0.6, abs=0.02)


def test_target_subset_age_groups():
    """A campaign targeting only one group leaves the other group's source untouched."""
    nk = [50_000.0, 50_000.0]
    model, initial = _two_group_model(nk)
    sim_dates = compute_simulation_dates("2025-01-01", "2025-01-31", dt=1.0)
    schedule = build_flat_count_schedule(sim_dates, "2025-01-05", "2025-01-15", 500.0)

    # Target only group B (index 1).
    _wire_vaccination(model, [(schedule, np.array([1]))], n_groups=2)

    results = model.run_simulations(
        start_date="2025-01-01",
        end_date="2025-01-31",
        Nsim=50,
        dt=1.0,
        initial_conditions_dict=initial,
        rng=np.random.default_rng(1),
    )

    # Group A receives no doses; Group B receives ~500/day for 11 days.
    a_totals = np.array([traj.transitions["X_to_X_vax_A"].sum() for traj in results.trajectories])
    b_totals = np.array([traj.transitions["X_to_X_vax_B"].sum() for traj in results.trajectories])
    assert np.all(a_totals == 0)
    expected = 500.0 * 11
    assert b_totals.mean() == pytest.approx(expected, rel=0.05)


def test_two_overlapping_campaigns_rates_add():
    """Two campaigns on the same source/target in overlapping windows: rates add per step."""
    model, initial = _minimal_model(initial_X=1_000_000.0)
    sim_dates = compute_simulation_dates("2025-01-01", "2025-01-31", dt=1.0)
    schedule_a = build_flat_count_schedule(sim_dates, "2025-01-05", "2025-01-15", 300.0)
    schedule_b = build_flat_count_schedule(sim_dates, "2025-01-10", "2025-01-20", 200.0)
    _wire_vaccination(
        model,
        [(schedule_a, np.array([0])), (schedule_b, np.array([0]))],
        n_groups=1,
    )

    results = model.run_simulations(
        start_date="2025-01-01",
        end_date="2025-01-31",
        Nsim=200,
        dt=1.0,
        initial_conditions_dict=initial,
        rng=np.random.default_rng(2),
    )
    per_step = np.stack([traj.transitions["X_to_X_vax_total"] for traj in results.trajectories])
    mean_per_step = per_step.mean(axis=0)

    # Per-step expected: 0 before 01-05, 300 in [01-05, 01-09], 500 in [01-10, 01-15],
    # 200 in [01-16, 01-20], 0 after.
    for i, d in enumerate(sim_dates):
        date_str = np.datetime_as_string(d, unit="D")
        if date_str < "2025-01-05" or date_str > "2025-01-20":
            assert per_step[:, i].sum() == 0, f"step {date_str} should be zero"
        elif "2025-01-05" <= date_str <= "2025-01-09":
            assert mean_per_step[i] == pytest.approx(300.0, rel=0.1), f"step {date_str}"
        elif "2025-01-10" <= date_str <= "2025-01-15":
            assert mean_per_step[i] == pytest.approx(500.0, rel=0.1), f"step {date_str}"
        else:  # 2025-01-16 .. 2025-01-20
            assert mean_per_step[i] == pytest.approx(200.0, rel=0.15), f"step {date_str}"


def test_rate_fn_coverage_cap_zeros_above_threshold():
    """A coverage cap zeros the campaign's contribution once vax compartments reach the threshold."""
    schedule = np.array([0.05])
    campaign = ResolvedCampaign(
        schedule_at_t=schedule,
        target_age_indices=np.array([0]),
        rate_based=True,
        coverage_threshold=500.0,  # Set threshold at 500 total vaccinated in the target group.
        vax_compartment_indices=np.array([1]),
    )
    rate_fn = make_vaccination_rate_fn([campaign], n_groups=1)

    # Below threshold (400 at target): full rate
    rate_below = rate_fn(
        {"source": "X", "denominator_sources": ("X",)},
        {"t": 0, "pop": np.array([[600.0], [400.0]]), "comp_indices": {"X": 0, "X_vax": 1}},
    )
    assert rate_below[0] == pytest.approx(0.05)

    # At threshold (500 at target): zero.
    rate_at = rate_fn(
        {"source": "X", "denominator_sources": ("X",)},
        {"t": 0, "pop": np.array([[500.0], [500.0]]), "comp_indices": {"X": 0, "X_vax": 1}},
    )
    assert rate_at[0] == pytest.approx(0.0)

    # Above threshold (600 at target): still zero.
    rate_above = rate_fn(
        {"source": "X", "denominator_sources": ("X",)},
        {"t": 0, "pop": np.array([[400.0], [600.0]]), "comp_indices": {"X": 0, "X_vax": 1}},
    )
    assert rate_above[0] == pytest.approx(0.0)


def test_rate_fn_coverage_cap_restricted_to_target_age_groups():
    """The cap sums vax compartments only over the campaign's target age groups."""
    schedule = np.array([0.05])
    # Target group A only (index 0). Group B's vax mass doesn't count.
    campaign = ResolvedCampaign(
        schedule_at_t=schedule,
        target_age_indices=np.array([0]),
        rate_based=True,
        coverage_threshold=300.0,
        vax_compartment_indices=np.array([1]),
    )
    rate_fn = make_vaccination_rate_fn([campaign], n_groups=2)
    # Group A vax = 100 < threshold; group B vax = 9999 doesn't count.
    rate = rate_fn(
        {"source": "X", "denominator_sources": ("X",)},
        {
            "t": 0,
            "pop": np.array([[500.0, 500.0], [100.0, 9999.0]]),
            "comp_indices": {"X": 0, "X_vax": 1},
        },
    )
    # The cap doesn't fire, so group A gets the rate; group B is outside target.
    assert rate[0] == pytest.approx(0.05)
    assert rate[1] == pytest.approx(0.0)
