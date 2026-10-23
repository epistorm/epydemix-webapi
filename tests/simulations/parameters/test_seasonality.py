"""Balcan seasonality through the simulation endpoint.

Tests here POST to `/api/v1/simulations` and assert on the returned parameter
series; pure-function tests of the Balcan math live in `test_seasonality.py`.

Composition with other transforms (scale, override, age-varying) lives in
`test_simulations_parameter_transforms.py`, and the dynamics consequence
(peak suppression) lives in `test_simulations_sir.py`.
"""

import pytest


def test_simulation_balcan_transform(client):
    """Balcan seasonality lands the right value at peak and trough dates.

    At `max_date` the multiplier is 1.0, so the parameter equals its baseline.
    At `min_date` the multiplier is val_min (with val_max=1.0).
    """
    baseline = 0.3
    request = {
        "model": {
            "preset": "SIR",
            "parameters": {"transmission_rate": baseline, "recovery_rate": 0.1},
        },
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-07-31",
            "Nsim": 3,
        },
        "parameter_transforms": [
            {
                "target_parameter": "transmission_rate",
                "method": "balcan",
                "max_date": "2024-01-15",  # Peak at January
                "min_date": "2024-07-15",  # Trough at July
                "max_value": 1.0,
                "min_value": 0.5,
            }
        ],
        "output": {"include_parameters": True},
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text

    params = response.json()["results"]["parameters"]
    dates = params["dates"]
    series = next(iter(params["data"]["transmission_rate"].values()))
    idx_max = dates.index("2024-01-15")
    idx_min = dates.index("2024-07-15")

    # With val_max=1.0, the trough multiplier is just val_min.
    assert series[idx_max] == pytest.approx(baseline * 1.0, abs=1e-9)
    assert series[idx_min] == pytest.approx(baseline * 0.5, abs=1e-9)

    # Away from max_date the multiplier is < 1, so values drop below baseline.
    idx_late = dates.index("2024-03-01")
    assert series[idx_late] < baseline


def test_simulation_balcan_transform_defaults_to_annual_period(client):
    """Omitting `min_date` yields a 365-day annual cycle for multi-season projection.

    With only `max_date` set, the period defaults to 365 days, so the
    multiplier peaks again exactly one year after `max_date`. This locks down
    the contract documented in the `min_date` field description.
    """
    baseline = 0.3
    request = {
        "model": {
            "preset": "SIR",
            "parameters": {"transmission_rate": baseline, "recovery_rate": 0.1},
        },
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2025-12-31",
            "Nsim": 1,
        },
        "parameter_transforms": [
            {
                "target_parameter": "transmission_rate",
                "method": "balcan",
                "max_date": "2024-01-15",
                "max_value": 1.0,
                "min_value": 0.5,
                # min_date intentionally omitted -> period defaults to 365 days.
            }
        ],
        "output": {"include_parameters": True},
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text

    params = response.json()["results"]["parameters"]
    dates = params["dates"]
    series = next(iter(params["data"]["transmission_rate"].values()))

    # First peak: at max_date itself, multiplier = 1.0.
    idx_peak_1 = dates.index("2024-01-15")
    assert series[idx_peak_1] == pytest.approx(baseline * 1.0, abs=1e-9)

    # Second peak: exactly 365 days later (period = 365), so 2025-01-14.
    idx_peak_2 = dates.index("2025-01-14")
    assert series[idx_peak_2] == pytest.approx(baseline * 1.0, abs=1e-9)

    # Trough at half-period offset (2024-07-15, ~183 days after max_date),
    # multiplier = val_min / val_max = 0.5.
    idx_trough = dates.index("2024-07-15")
    assert series[idx_trough] == pytest.approx(baseline * 0.5, abs=1e-3)

    # Series stays within [baseline * 0.5, baseline * 1.0] throughout.
    assert min(series) == pytest.approx(baseline * 0.5, abs=1e-3)
    assert max(series) == pytest.approx(baseline * 1.0, abs=1e-9)
