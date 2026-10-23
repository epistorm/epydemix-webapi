"""End-to-end tests specific to the ``flat_count`` rollout.

Validation, custom-model wiring, flow-level behavior (dose sinks,
multi-target), coverage caps, and metadata are exercised in
``test_vaccination.py`` (they are agnostic to the rollout strategy but
happen to use ``flat_count`` as the convenient driver).
"""

import pytest


def _custom_vax_model_request(**overrides):
    """Minimal custom S/S_vax/I model with a flat_count vaccination campaign."""
    request = {
        "model": {
            "compartments": ["S", "S_vax", "I"],
            "parameters": {
                "transmission_rate": 0.3,
                "recovery_rate": 0.0,
            },
            "transitions": [
                {
                    "source": "S",
                    "target": "I",
                    "kind": "mediated",
                    "params": ["transmission_rate", "I"],
                },
                {
                    "source": "S_vax",
                    "target": "I",
                    "kind": "mediated",
                    "params": ["transmission_rate", "I"],
                },
            ],
        },
        "population": {
            "source": "custom",
            "name": "tiny",
            "age_groups": {"all": 1_000_000},
            "contact_matrices": {"all": [[1.0]]},
        },
        "simulation": {
            "start_date": "2025-01-01",
            "end_date": "2025-01-31",
            "Nsim": 5,
            "seed": 7,
        },
        "initial_conditions": {
            "method": "absolute",
            "compartments": {
                "S": [1_000_000],
                "S_vax": [0],
                "I": [0],
            },
        },
        "vaccination": {
            "flows": [{"source": "S", "target": "S_vax"}],
            "campaigns": [
                {
                    "start_date": "2025-01-05",
                    "end_date": "2025-01-15",
                    "rollout": {"type": "flat_count", "daily_doses": 10_000},
                }
            ],
        },
    }
    for key, value in overrides.items():
        request[key] = value
    return request


def test_vaccination_dose_count_close_to_expected(client):
    """Cumulative S to S_vax transitions should be close to daily_doses * days."""
    request = _custom_vax_model_request()
    request["simulation"]["Nsim"] = 20
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    data = response.json()
    transitions = data["results"]["transitions"]["data"]["S_to_S_vax"]

    quantile_data = next(iter(transitions.values()))
    median_key = "median" if "median" in quantile_data else "0.5"
    series = quantile_data[median_key]
    dates = data["results"]["transitions"]["dates"]
    in_window = [v for d, v in zip(dates, series) if "2025-01-05" <= d <= "2025-01-15"]

    # For 11 days, we expect a total of 10000 * 11 daily doses.
    expected = 10_000 * 11
    cumulative = sum(in_window)
    assert cumulative == pytest.approx(expected, rel=0.05)
