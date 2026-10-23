"""Unit tests specific to the ``fixed_rate`` rollout strategy.

Covers the rate-based schedule builder and the rate-fn behavior that
differs from the count-based path (no division by the eligible pool).
Strategy-agnostic rate-fn behavior and coverage-cap tests live in
``tests/test_vaccination.py``.
"""

import numpy as np
import pytest
from epydemix.utils.utils import compute_simulation_dates

from app.utils.vaccination import (
    ResolvedCampaign,
    build_fixed_rate_schedule,
    make_vaccination_rate_fn,
)


def test_fixed_rate_schedule_zero_outside_window():
    """`build_fixed_rate_schedule` puts the configured rate inside the window, 0 outside."""
    dates = compute_simulation_dates("2025-01-01", "2025-01-31", dt=1.0)
    schedule = build_fixed_rate_schedule(dates, "2025-01-10", "2025-01-20", 0.05)
    assert schedule.shape == (len(dates),)
    for i, d in enumerate(dates):
        date_str = np.datetime_as_string(d, unit="D")
        # Inside the window: 0.05
        if "2025-01-10" <= date_str <= "2025-01-20":
            assert schedule[i] == 0.05
        # Outside the window: 0.0
        else:
            assert schedule[i] == 0.0


def test_rate_fn_fixed_rate_independent_of_pool():
    """Rate-based campaigns apply the schedule value directly; no division by pool size."""
    schedule = np.array([0.02, 0.02, 0.0])
    campaign = ResolvedCampaign(
        schedule_at_t=schedule,
        target_age_indices=np.array([0]),
        rate_based=True,
    )
    rate_fn = make_vaccination_rate_fn([campaign], n_groups=1)

    # Tiny pool
    rate_small = rate_fn(
        {"source": "X", "denominator_sources": ("X",)},
        {"t": 0, "pop": np.array([[5.0], [0.0]]), "comp_indices": {"X": 0, "X_vax": 1}},
    )
    # Huge pool
    rate_large = rate_fn(
        {"source": "X", "denominator_sources": ("X",)},
        {"t": 0, "pop": np.array([[5_000_000.0], [0.0]]), "comp_indices": {"X": 0, "X_vax": 1}},
    )

    # Pool size will not affect the rate
    assert rate_small[0] == pytest.approx(0.02)
    assert rate_large[0] == pytest.approx(0.02)

    # Outside the window: zero regardless of mode
    rate_off = rate_fn(
        {"source": "X", "denominator_sources": ("X",)},
        {"t": 2, "pop": np.array([[100.0], [0.0]]), "comp_indices": {"X": 0, "X_vax": 1}},
    )
    assert rate_off[0] == pytest.approx(0.0)
