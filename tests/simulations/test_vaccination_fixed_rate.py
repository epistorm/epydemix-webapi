"""End-to-end tests specific to the ``fixed_rate`` rollout."""

import numpy as np
import pytest


def _fixed_rate_request(rate: float = 0.01):
    """Custom S/S_vax model driven by a fixed_rate campaign over the whole sim window."""
    return {
        "model": {
            "compartments": ["S", "S_vax"],
            "parameters": {"k": 0.0},
            "transitions": [],
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
            "Nsim": 30,
            "seed": 23,
        },
        "initial_conditions": {
            "method": "absolute",
            "compartments": {"S": [1_000_000], "S_vax": [0]},
        },
        "vaccination": {
            "flows": [{"source": "S", "target": "S_vax"}],
            "campaigns": [
                {
                    "start_date": "2025-01-01",
                    "end_date": "2025-01-31",
                    "rollout": {"type": "fixed_rate", "rate": rate},
                }
            ],
        },
        "output": {"include_trajectories": True},
    }


def test_fixed_rate_decay_matches_analytic(client):
    """fixed_rate produces S(t) decay tracking S0 * exp(-r*t) within stochastic tolerance.

    With Nsim=30 and S0=1e6, per-step SE is small but not zero; the median
    over the runs is compared at the window endpoints against the closed-form
    decay. The reported series starts at t=1 (one step after the initial
    conditions), so the analytic value uses the same step offset.
    """
    rate = 0.02
    response = client.post("/api/v1/simulations", json=_fixed_rate_request(rate))
    assert response.status_code == 200, response.text
    data = response.json()
    quantile_data = next(iter(data["results"]["compartments"]["data"]["S"].values()))
    median_key = "median" if "median" in quantile_data else "0.5"
    s_series = quantile_data[median_key]
    dates = data["results"]["compartments"]["dates"]
    n_steps = len(dates)
    # Day-1 median should match one step of decay.
    assert s_series[0] == pytest.approx(1_000_000.0 * np.exp(-rate * 1), rel=0.01)
    # Final step should match n_steps days of decay.
    assert s_series[-1] == pytest.approx(1_000_000.0 * np.exp(-rate * n_steps), rel=0.05)


def test_fixed_rate_metadata_echoed(client):
    """metadata.vaccination round-trips the fixed_rate rollout block."""
    response = client.post("/api/v1/simulations", json=_fixed_rate_request(0.01))
    assert response.status_code == 200
    rollout = response.json()["metadata"]["vaccination"]["campaigns"][0]["rollout"]
    assert rollout["type"] == "fixed_rate"
    assert rollout["rate"] == 0.01


def _spontaneous_equivalent_request(rate: float = 0.02):
    """Same model/population/window as `_fixed_rate_request`, but the S -> S_vax
    flow is declared as a plain spontaneous transition at `rate`, with no
    `vaccination` block. Used to verify that the fixed_rate rollout is
    mathematically identical to a spontaneous transition.
    """
    return {
        "model": {
            "compartments": ["S", "S_vax"],
            "parameters": {"vax_rate": rate},
            "transitions": [
                {
                    "source": "S",
                    "target": "S_vax",
                    "kind": "spontaneous",
                    "params": ["vax_rate"],
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
            "Nsim": 30,
            "seed": 23,
        },
        "initial_conditions": {
            "method": "absolute",
            "compartments": {"S": [1_000_000], "S_vax": [0]},
        },
        "output": {"include_trajectories": True},
    }


def test_fixed_rate_matches_spontaneous_transition(client):
    """A fixed_rate campaign produces the same dynamics as an equivalent spontaneous transition.

    Same population, window, seed, and Nsim. The fixed_rate path drives
    S -> S_vax via the vaccination machinery; the spontaneous path declares
    the same edge directly as a model transition at the same per-day rate.
    The two should agree on the median S(t) and S_vax(t) within stochastic
    tolerance.
    """
    rate = 0.02
    vax_resp = client.post("/api/v1/simulations", json=_fixed_rate_request(rate))
    spo_resp = client.post("/api/v1/simulations", json=_spontaneous_equivalent_request(rate))
    assert vax_resp.status_code == 200, vax_resp.text
    assert spo_resp.status_code == 200, spo_resp.text

    def _median_series(resp, compartment: str):
        comp = resp.json()["results"]["compartments"]["data"][compartment]
        quantile_data = next(iter(comp.values()))
        median_key = "median" if "median" in quantile_data else "0.5"
        return quantile_data[median_key]

    vax_S = _median_series(vax_resp, "S")
    spo_S = _median_series(spo_resp, "S")
    vax_Svax = _median_series(vax_resp, "S_vax")
    spo_Svax = _median_series(spo_resp, "S_vax")

    # Endpoints must agree; the analytic decay is S0 * exp(-rate * t)
    assert vax_S[0] == pytest.approx(spo_S[0], rel=0.01)
    assert vax_S[-1] == pytest.approx(spo_S[-1], rel=0.05)
    assert vax_Svax[-1] == pytest.approx(spo_Svax[-1], rel=0.05)

    # Whole trajectory shape should match
    for i in range(1, len(vax_S)):
        assert vax_S[i] == pytest.approx(spo_S[i], rel=0.05), f"S diverges at step {i}"
