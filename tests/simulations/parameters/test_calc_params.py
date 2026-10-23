"""Calc-param (expression) parameters and transforms that target them.

Tests here POST to `/api/v1/simulations` and assert on the returned parameter
series; they are integration tests against the running pipeline, not pure-function
unit tests. Exercises the expression-evaluator path: parameters defined as string
expressions like `"a * 2"` resolve correctly, and transforms targeting either
the source parameter or the calc-param both propagate.
"""

import pytest


def _calc_param_sir_request(parameters: dict) -> dict:
    """Custom 3-compartment SIR substrate with a user calc-param baked in."""
    return {
        "model": {
            "compartments": ["S", "I", "R"],
            "parameters": parameters,
            "transitions": [
                {
                    "source": "S",
                    "target": "I",
                    "kind": "mediated",
                    "params": ["transmission_rate", "I"],
                },
                {"source": "I", "target": "R", "kind": "spontaneous", "params": "recovery_rate"},
            ],
        },
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "Nsim": 2,
            "seed": 1,
        },
        "output": {"include_parameters": True},
    }


def test_transform_on_calc_param_target_accepted(client):
    """A scale transform targeting a calc-param applies in the calc-pass."""
    request = _calc_param_sir_request(
        {"a": 0.3, "b": "a * 2", "transmission_rate": 0.3, "recovery_rate": 0.1}
    )
    request["parameter_transforms"] = [
        {
            "target_parameter": "b",
            "method": "scale",
            "start_date": "2024-01-10",
            "end_date": "2024-01-20",
            "factor": 0.5,
        }
    ]
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]
    dates = params["dates"]
    series = next(iter(params["data"]["b"].values()))
    in_window = [v for d, v in zip(dates, series) if "2024-01-10" <= d <= "2024-01-20"]
    out_of_window = [v for d, v in zip(dates, series) if d < "2024-01-10" or d > "2024-01-20"]
    # Inside: a*2*0.5 = 0.3*2*0.5 = 0.3
    # Outside: a*2 = 0.6
    assert in_window == pytest.approx([0.3] * len(in_window), abs=1e-9)
    assert out_of_window == pytest.approx([0.6] * len(out_of_window), abs=1e-9)


def test_override_on_calc_param_target(client):
    """An override transform on a calc-param replaces the value in-window."""
    request = _calc_param_sir_request(
        {"a": 0.3, "b": "a * 2", "transmission_rate": 0.3, "recovery_rate": 0.1}
    )
    request["parameter_transforms"] = [
        {
            "target_parameter": "b",
            "method": "override",
            "start_date": "2024-01-10",
            "end_date": "2024-01-20",
            "value": 99.0,
        }
    ]
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]
    dates = params["dates"]
    series = next(iter(params["data"]["b"].values()))
    in_window = [v for d, v in zip(dates, series) if "2024-01-10" <= d <= "2024-01-20"]
    out_of_window = [v for d, v in zip(dates, series) if d < "2024-01-10" or d > "2024-01-20"]
    assert in_window == pytest.approx([99.0] * len(in_window), abs=1e-9)
    assert out_of_window == pytest.approx([0.6] * len(out_of_window), abs=1e-9)


def test_override_composes_after_scale(client):
    """Scale then override on the same window: override wins."""
    request = _calc_param_sir_request({"transmission_rate": 1.0, "recovery_rate": 0.1})
    request["parameter_transforms"] = [
        {
            "target_parameter": "transmission_rate",
            "method": "scale",
            "start_date": "2024-01-10",
            "end_date": "2024-01-20",
            "factor": 2.0,
        },
        {
            "target_parameter": "transmission_rate",
            "method": "override",
            "start_date": "2024-01-10",
            "end_date": "2024-01-20",
            "value": 5.0,
        },
    ]
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]
    dates = params["dates"]
    series = next(iter(params["data"]["transmission_rate"].values()))
    in_window = [v for d, v in zip(dates, series) if "2024-01-10" <= d <= "2024-01-20"]
    out_of_window = [v for d, v in zip(dates, series) if d < "2024-01-10" or d > "2024-01-20"]
    assert in_window == pytest.approx([5.0] * len(in_window), abs=1e-9)
    assert out_of_window == pytest.approx([1.0] * len(out_of_window), abs=1e-9)


def test_override_on_source_propagates_to_calc_param(client):
    """Step 0b regression: an override on a source parameter is visible to calc-params."""
    request = _calc_param_sir_request(
        {"a": 1.0, "b": "a * 2", "transmission_rate": 0.3, "recovery_rate": 0.1}
    )
    request["parameter_transforms"] = [
        {
            "target_parameter": "a",
            "method": "override",
            "start_date": "2024-01-10",
            "end_date": "2024-01-20",
            "value": 5.0,
        }
    ]
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]
    dates = params["dates"]
    series_b = next(iter(params["data"]["b"].values()))
    in_window = [v for d, v in zip(dates, series_b) if "2024-01-10" <= d <= "2024-01-20"]
    out_of_window = [v for d, v in zip(dates, series_b) if d < "2024-01-10" or d > "2024-01-20"]
    assert in_window == pytest.approx([10.0] * len(in_window), abs=1e-9)
    assert out_of_window == pytest.approx([2.0] * len(out_of_window), abs=1e-9)
