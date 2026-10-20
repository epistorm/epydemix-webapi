"""Tests for standalone epydemix Python exports."""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

SIMPLE_SIMULATION = {
    "model": {
        "preset": "SIR",
        "parameters": {
            "transmission_rate": 0.3,
            "recovery_rate": 0.1,
        },
    },
    "population": {
        "source": "custom",
        "name": "Homogeneous",
        "age_groups": {"all": 1000},
        "contact_matrices": {"all": [[1.0]]},
    },
    "simulation": {
        "start_date": "2025-01-01",
        "end_date": "2025-01-03",
        "Nsim": 1,
        "seed": 42,
    },
}


def _assert_python_response(response) -> str:
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/x-python")
    assert "attachment; filename=" in response.headers["content-disposition"]
    compile(response.text, "<export>", "exec")
    return response.text


def _run_exported_source(source: str, tmp_path):
    script = tmp_path / "simulation.py"
    script.write_text(source)
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _assert_csv_matches_api(native, api_section):
    expected_dates = api_section["dates"]
    for variable, age_groups in api_section["data"].items():
        for age_group, quantiles in age_groups.items():
            column = f"{variable}_{age_group}"
            assert column in native.columns
            for quantile, expected_values in quantiles.items():
                rows = native.loc[np.isclose(native["quantile"], float(quantile))]
                assert rows["date"].tolist() == expected_dates
                np.testing.assert_allclose(
                    rows[column].to_numpy(),
                    expected_values,
                    rtol=0,
                    atol=0,
                )


def _assert_export_matches_api(request, tmp_path, client) -> str:
    source = _assert_python_response(
        client.post("/api/v1/simulations/export/python", json=request)
    )
    completed = _run_exported_source(source, tmp_path)
    assert completed.returncode == 0, completed.stderr

    api_response = client.post("/api/v1/simulations", json=request)
    assert api_response.status_code == 200
    body = api_response.json()
    assert body["status"] == "completed", body.get("error")

    _assert_csv_matches_api(
        pd.read_csv(tmp_path / "compartments.csv", float_precision="round_trip"),
        body["results"]["compartments"],
    )
    _assert_csv_matches_api(
        pd.read_csv(tmp_path / "transitions.csv", float_precision="round_trip"),
        body["results"]["transitions"],
    )
    return source


def test_export_simulation_is_standalone_native_python(client):
    source = _assert_python_response(
        client.post("/api/v1/simulations/export/python", json=SIMPLE_SIMULATION)
    )

    assert "from epydemix import EpiModel" in source
    assert "model.run_simulations(" in source
    assert "from app" not in source
    assert "calculate_dominant_contact_eigenvalue" not in source
    assert "apply_balcan_seasonality" not in source


def test_exported_custom_simulation_matches_api(tmp_path, client):
    _assert_export_matches_api(SIMPLE_SIMULATION, tmp_path, client)
    assert (tmp_path / "compartments.csv").exists()
    assert (tmp_path / "transitions.csv").exists()


def test_export_r0_seasonality_and_scaling_match_api(tmp_path, client):
    request = {
        **SIMPLE_SIMULATION,
        "model": {
            "preset": "SEIR",
            "parameters": {
                "R0": 2.5,
                "incubation_period": 3.0,
                "infectious_period": 2.5,
            },
        },
        "simulation": {
            **SIMPLE_SIMULATION["simulation"],
            "Nsim": 3,
        },
        "parameter_transforms": [
            {
                "target_parameter": "transmission_rate",
                "method": "balcan",
                "max_date": "2025-01-01",
                "min_date": "2025-07-01",
                "min_value": 0.85,
            },
            {
                "target_parameter": "transmission_rate",
                "method": "scale",
                "start_date": "2025-01-02",
                "end_date": "2025-01-03",
                "factor": 0.7,
            },
        ],
    }

    source = _assert_export_matches_api(request, tmp_path, client)

    assert "def calculate_dominant_contact_eigenvalue" in source
    assert "def calculate_transmission_rate_from_r0" in source
    assert "def apply_balcan_seasonality" in source
    assert "def apply_parameter_scaling" in source
    assert "calculate_transmission_rate_from_r0(" in source


@pytest.mark.parametrize("preset", ["SIR", "SEIR", "SIS"])
def test_export_basic_preset_defaults_match_api(preset, tmp_path, client):
    request = {
        **SIMPLE_SIMULATION,
        "model": {"preset": preset},
        "population": {
            "source": "custom",
            "name": "Two groups",
            "age_groups": {"younger": 800, "older": 200},
            "contact_matrices": {"all": [[2.0, 1.0], [1.0, 1.5]]},
        },
        "simulation": {
            **SIMPLE_SIMULATION["simulation"],
            "end_date": "2025-01-10",
            "Nsim": 3,
        },
    }

    source = _assert_export_matches_api(request, tmp_path, client)

    assert "model.add_parameter(parameter_name='R0', value=2.5)" in source
    assert "calculate_transmission_rate_from_r0(" in source


def test_export_vaccination_rollouts_match_api(tmp_path, client):
    request = {
        **SIMPLE_SIMULATION,
        "model": {
            "preset": "V-SEIR",
            "parameters": {
                "R0": 2.0,
                "incubation_period": 3.0,
                "infectious_period": 4.0,
                "VE_S": 0.7,
            },
        },
        "simulation": {
            **SIMPLE_SIMULATION["simulation"],
            "Nsim": 3,
        },
        "vaccination": {
            "campaigns": [
                {
                    "start_date": "2025-01-01",
                    "end_date": "2025-01-03",
                    "rollout": {"type": "flat_count", "daily_doses": 10},
                    "coverage": {
                        "fraction": 0.5,
                        "compartments": [
                            "Susceptible_vax",
                            "Exposed_vax",
                            "Infected_vax",
                            "Recovered_vax",
                        ],
                    },
                },
                {
                    "start_date": "2025-01-02",
                    "end_date": "2025-01-03",
                    "rollout": {"type": "fixed_rate", "rate": 0.005},
                },
            ]
        },
    }
    source = _assert_export_matches_api(request, tmp_path, client)
    assert "def apply_vaccination_campaigns" in source
    assert 'model.register_transition_kind("vaccination"' in source


def test_export_override_intervention_and_subdaily_match_api(tmp_path, client):
    request = {
        **SIMPLE_SIMULATION,
        "simulation": {
            "start_date": "2025-01-01",
            "end_date": "2025-01-02",
            "Nsim": 3,
            "dt": 0.5,
            "seed": 7,
        },
        "interventions": [
            {
                "layer_name": "all",
                "start_date": "2025-01-01",
                "end_date": "2025-01-02",
                "reduction_factor": 0.8,
            }
        ],
        "parameter_transforms": [
            {
                "target_parameter": "transmission_rate",
                "method": "scale",
                "start_date": "2025-01-01",
                "end_date": "2025-01-01",
                "factor": 0.5,
            },
            {
                "target_parameter": "recovery_rate",
                "method": "override",
                "start_date": "2025-01-02",
                "end_date": "2025-01-02",
                "value": 0.2,
            },
        ],
    }
    source = _assert_export_matches_api(request, tmp_path, client)
    assert "def apply_parameter_scaling" in source
    assert "def apply_parameter_override" in source
    assert "timedelta(days=1)" in source


def test_export_rejects_unsafe_calculated_parameter(client):
    request = {
        **SIMPLE_SIMULATION,
        "model": {
            "preset": "SIR",
            "parameters": {"transmission_rate": "__import__('os').getcwd()"},
        },
    }
    response = client.post("/api/v1/simulations/export/python", json=request)
    assert response.status_code == 422


def test_export_rejects_unknown_transform_target(client):
    request = {
        **SIMPLE_SIMULATION,
        "parameter_transforms": [
            {
                "target_parameter": "typo",
                "method": "scale",
                "start_date": "2025-01-01",
                "end_date": "2025-01-02",
                "factor": 0.5,
            }
        ],
    }
    response = client.post("/api/v1/simulations/export/python", json=request)
    assert response.status_code == 422


def test_export_population_list(client):
    source = _assert_python_response(client.get("/api/v1/populations/export/python"))
    assert "get_available_locations(" in source
    assert "data_version=\"v1.2.0\"" in source


def test_export_population_detail(client):
    source = _assert_python_response(
        client.get(
            "/api/v1/populations/United_States/export/python",
            params={"contacts_source": "mistry_2021"},
        )
    )
    assert "load_epydemix_population(" in source
    assert "population_name='United_States'" in source
    assert "contacts_source='mistry_2021'" in source


def test_export_population_contacts(client):
    source = _assert_python_response(
        client.get(
            "/api/v1/populations/United_States/contacts/export/python",
            params=[("layers", "home"), ("layers", "work")],
        )
    )
    assert "def calculate_spectral_radius" in source
    assert "layers=['home', 'work']" in source


def test_export_custom_population(client):
    response = client.post(
        "/api/v1/populations/export/python",
        json={
            "source": "custom",
            "name": "Two groups",
            "age_groups": {"younger": 80, "older": 20},
            "contact_matrices": {"all": [[2.0, 1.0], [1.0, 1.5]]},
        },
    )
    source = _assert_python_response(response)
    assert "Population(name='Two groups')" in source
    assert "population.add_contact_matrix(" in source


def test_export_model_preset(client):
    source = _assert_python_response(
        client.get("/api/v1/models/presets/SIR/export/python")
    )
    assert "model = EpiModel(" in source
    assert "source='Susceptible'" in source


def test_export_unknown_model_preset(client):
    response = client.get("/api/v1/models/presets/UNKNOWN/export/python")
    assert response.status_code == 404
