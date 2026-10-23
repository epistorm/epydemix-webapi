"""Unit tests for the Balcan seasonality math.

Adapted from epymodelingsuite/tests/test_seasonality.py.
"""

import datetime as dt
import math

import numpy as np
import pytest

from app.utils.seasonality import (
    _calc_seasonality_balcan_at_t,
    calc_seasonality_balcan_at_date,
    get_seasonal_transmission_balcan,
)


def test_calc_seasonality_balcan_at_t_peak_and_min():
    """Peak at t_max equals 1.0; trough at half-period equals val_min/val_max."""
    val_min, val_max = 0.6, 1.4
    period = 365
    t_max = 120

    vals = [
        _calc_seasonality_balcan_at_t(t, t_max, val_min, val_max, period)
        for t in range(0, period + 1)
    ]

    # Peak index matches t_max
    assert int(np.argmax(vals)) == t_max

    # Peak value is exactly 1.0
    val_peak = _calc_seasonality_balcan_at_t(t_max, t_max, val_min, val_max, period)
    assert math.isclose(val_peak, 1.0, rel_tol=0, abs_tol=1e-8)

    # Minimum index is half a period after t_max
    assert int(np.argmin(vals)) == t_max + period // 2

    # Minimum value equals val_min/val_max
    expected_min = val_min / val_max
    assert math.isclose(min(vals), expected_min, rel_tol=0, abs_tol=1e-4)

    # Whole period stays inside [val_min/val_max, 1.0]
    assert min(vals) >= expected_min - 1e-12
    assert max(vals) <= 1.0 + 1e-12


@pytest.mark.parametrize(
    "val_min,val_max,period,t_offset",
    [
        (0.2, 1.0, 365, 0),
        (0.5, 1.5, 360, 17),
        (0.9, 1.1, 180, 73),
    ],
)
def test_calc_seasonality_balcan_at_date_matches_calc(val_min, val_max, period, t_offset):
    """The date-version agrees with the t-version when ``period`` is explicit."""
    date_start = dt.date(2020, 1, 1)
    date_tmax = date_start + dt.timedelta(days=50)
    date_t = date_start + dt.timedelta(days=50 + t_offset)

    v_date = calc_seasonality_balcan_at_date(
        date_t=date_t,
        date_start=date_start,
        date_tmax=date_tmax,
        val_min=val_min,
        val_max=val_max,
        period=period,
    )

    t_days = (date_t - date_start).days
    t_max_days = (date_tmax - date_start).days
    v_expected = _calc_seasonality_balcan_at_t(t_days, t_max_days, val_min, val_max, period)

    assert math.isclose(v_date, v_expected, rel_tol=0, abs_tol=1e-12)


def test_calc_seasonality_balcan_at_date_derives_period_from_tmin():
    """When ``period`` is None and ``date_tmin`` is given, period = 2*|tmin - tmax|."""
    val_min, val_max = 0.6, 1.2
    date_start = dt.date(2023, 1, 1)
    date_tmax = dt.date(2023, 3, 1)
    date_tmin = dt.date(2023, 9, 1)
    date_t = dt.date(2023, 6, 1)

    v = calc_seasonality_balcan_at_date(
        date_t=date_t,
        date_start=date_start,
        date_tmax=date_tmax,
        date_tmin=date_tmin,
        val_min=val_min,
        val_max=val_max,
        period=None,
    )

    t_days = (date_t - date_start).days
    t_max_days = (date_tmax - date_start).days
    t_min_days = (date_tmin - date_start).days
    derived_period = 2 * abs(t_min_days - t_max_days)
    v_expected = _calc_seasonality_balcan_at_t(t_days, t_max_days, val_min, val_max, derived_period)

    assert math.isclose(v, v_expected, rel_tol=0, abs_tol=1e-12)


def test_calc_seasonality_balcan_at_date_period_overrides_tmin():
    """Explicit ``period`` wins even when ``date_tmin`` is also provided."""
    val_min, val_max = 0.4, 1.6
    date_start = dt.date(2022, 1, 1)
    date_tmax = dt.date(2022, 2, 1)
    date_tmin = dt.date(2022, 8, 1)
    forced_period = 200
    date_t = dt.date(2022, 5, 1)

    v = calc_seasonality_balcan_at_date(
        date_t=date_t,
        date_start=date_start,
        date_tmax=date_tmax,
        date_tmin=date_tmin,
        val_min=val_min,
        val_max=val_max,
        period=forced_period,
    )

    t_days = (date_t - date_start).days
    t_max_days = (date_tmax - date_start).days
    v_expected = _calc_seasonality_balcan_at_t(t_days, t_max_days, val_min, val_max, forced_period)

    assert math.isclose(v, v_expected, rel_tol=0, abs_tol=1e-12)


def test_get_seasonal_transmission_balcan_end_to_end():
    """Wrapper yields right length, value at tmax is the max, trough at half-period offset."""
    date_start = dt.date(2020, 1, 1)
    date_stop = dt.date(2020, 12, 31)
    date_tmax = dt.date(2020, 6, 1)
    val_min, val_max = 0.7, 1.3

    dates, values = get_seasonal_transmission_balcan(
        date_start=date_start,
        date_stop=date_stop,
        date_tmax=date_tmax,
        val_min=val_min,
        val_max=val_max,
        date_tmin=None,
    )

    # Length matches inclusive day range
    n_days = (date_stop - date_start).days + 1
    assert len(dates) == len(values) == n_days

    # Value at the tmax index is exactly the maximum (= 1.0)
    idx_tmax = (date_tmax - date_start).days
    assert math.isclose(values[idx_tmax], 1.0, rel_tol=0, abs_tol=1e-12)
    assert values[idx_tmax] == pytest.approx(max(values), abs=1e-12)

    # Trough at half-period offset (default period = 365)
    idx_tmin = idx_tmax + 365 // 2
    if idx_tmin < len(values):
        expected_min = val_min / val_max
        assert values[idx_tmin] == pytest.approx(expected_min, abs=1e-4)


def test_balcan_transform_writes_expected_array_into_model():
    """Integration: applying a balcan transform to a preset writes the right array into
    ``model.parameters[target]`` — value at max-date index equals ``baseline * 1.0``,
    value at min-date index equals ``baseline * (val_min/val_max)``.
    """
    from app.api.v1.schemas.simulation import (
        BalcanTransform,
        BuiltinPopulationConfig,
        ModelConfig,
        SimulationConfig,
    )
    from app.services.model_service import create_model
    from app.services.parameter_transforms_service import apply_parameter_transforms_sources
    from app.services.population_service import setup_population

    baseline = 0.3
    val_min, val_max = 0.1, 1.0  # multiplier in [0.1, 1.0]

    model, _, _ = create_model(
        ModelConfig(preset="SIR", parameters={"transmission_rate": baseline})
    )
    setup_population(model, BuiltinPopulationConfig(name="United_States"))

    sim_cfg = SimulationConfig(start_date="2024-01-01", end_date="2024-12-31", Nsim=1)
    transform = BalcanTransform(
        target_parameter="transmission_rate",
        method="balcan",
        max_date="2024-01-15",
        min_date="2024-07-15",
        max_value=val_max,
        min_value=val_min,
    )
    apply_parameter_transforms_sources(model, [transform], sim_cfg)

    arr = model.parameters["transmission_rate"]
    assert hasattr(arr, "__len__")
    assert len(arr) == 366  # Jan 1 2024 .. Dec 31 2024 inclusive (leap year)

    # Value at the max-date index ≈ baseline * 1.0
    idx_max = (dt.date(2024, 1, 15) - dt.date(2024, 1, 1)).days
    assert arr[idx_max] == pytest.approx(baseline * 1.0, abs=1e-10)

    # Value at the min-date index ≈ baseline * (val_min/val_max)
    idx_min = (dt.date(2024, 7, 15) - dt.date(2024, 1, 1)).days
    assert arr[idx_min] == pytest.approx(baseline * (val_min / val_max), abs=1e-10)
