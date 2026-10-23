"""Age-varying base parameters: list-valued model parameters broadcast per age group.

Tests here POST to `/api/v1/simulations` and assert on the returned per-age-group
parameter series; they are integration tests against the running pipeline, not
pure-function unit tests.
"""

import pytest

_AGE_GROUP_MAPPING_5 = {
    "0-4": ["0-4"],
    "5-17": ["5-9", "10-14", "15-19"],
    "18-49": ["20-24", "25-29", "30-34", "35-39", "40-44", "45-49"],
    "50-64": ["50-54", "55-59", "60-64"],
    "65+": ["65-69", "70-74", "75+"],
}


def test_simulation_age_varying_parameters_preset(client):
    """Age-varying base parameters land in the model as constant per-age-group series."""
    expected_transmission = [0.35, 0.35, 0.35, 0.30, 0.25]
    expected_recovery = [0.10, 0.10, 0.10, 0.08, 0.06]
    request = {
        "model": {
            "preset": "SIR",
            "parameters": {
                "transmission_rate": expected_transmission,
                "recovery_rate": expected_recovery,
            },
        },
        "population": {
            "name": "United_States",
            "contacts_source": "prem_2021",
            "age_group_mapping": _AGE_GROUP_MAPPING_5,
        },
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-15",
            "Nsim": 3,
        },
        "output": {"include_parameters": True},
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text

    params_data = response.json()["results"]["parameters"]["data"]
    for name, expected in (
        ("transmission_rate", expected_transmission),
        ("recovery_rate", expected_recovery),
    ):
        groups = list(params_data[name].keys())
        assert len(groups) == 5, f"{name}: expected 5 age groups, got {groups}"
        for group, expected_val in zip(groups, expected):
            series = params_data[name][group]
            assert series == pytest.approx([expected_val] * len(series), abs=1e-12), (
                f"{name}[{group}] = {series}, expected constant {expected_val}"
            )


def test_simulation_age_varying_parameters_custom(client):
    """Age-varying base parameters work the same way on a custom (non-preset) model."""
    expected_beta = [0.35, 0.35, 0.30, 0.25, 0.20]
    request = {
        "model": {
            "compartments": ["S", "I", "R"],
            "parameters": {
                "beta": expected_beta,
                "gamma": 0.1,
            },
            "transitions": [
                {"source": "S", "target": "I", "kind": "mediated", "params": ["beta", "I"]},
                {"source": "I", "target": "R", "kind": "spontaneous", "params": "gamma"},
            ],
        },
        "population": {
            "name": "United_States",
            "contacts_source": "prem_2021",
            "age_group_mapping": _AGE_GROUP_MAPPING_5,
        },
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-15",
            "Nsim": 3,
        },
        "output": {"include_parameters": True},
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text

    beta = response.json()["results"]["parameters"]["data"]["beta"]
    groups = list(beta.keys())
    assert len(groups) == 5
    for group, expected_val in zip(groups, expected_beta):
        series = beta[group]
        assert series == pytest.approx([expected_val] * len(series), abs=1e-12)


def test_simulation_age_varying_length_mismatch(client):
    """Length of an age-varying list must match population num_groups."""
    request = {
        "model": {
            "preset": "SIR",
            "parameters": {"transmission_rate": [0.3, 0.2]},  # only 2 entries
        },
        "population": {
            "name": "United_States",
            "contacts_source": "prem_2021",
            "age_group_mapping": _AGE_GROUP_MAPPING_5,  # 5 groups
        },
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
            "Nsim": 2,
        },
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "transmission_rate" in detail
    assert "5" in detail
