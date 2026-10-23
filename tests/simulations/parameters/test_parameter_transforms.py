"""Core `parameter_transforms` pipeline, exercised end-to-end through the simulation endpoint.

Tests here POST to `/api/v1/simulations` and assert on the returned parameter
series (via `output.include_parameters`). They are integration tests against the
running pipeline, not pure-function unit tests; for pure function tests of the
underlying math, see `test_seasonality.py`, `test_vaccination.py`, etc.

Single-concern tests live in their own files:
- pure balcan in test_simulations_seasonality.py
- age-varying base parameters in test_simulations_age_varying.py
- calc-param transforms in test_simulations_calc_params.py

Tests that compose transforms with age-varying base parameters stay here.
"""

import pytest

_AGE_GROUP_MAPPING_5 = {
    "0-4": ["0-4"],
    "5-17": ["5-9", "10-14", "15-19"],
    "18-49": ["20-24", "25-29", "30-34", "35-39", "40-44", "45-49"],
    "50-64": ["50-54", "55-59", "60-64"],
    "65+": ["65-69", "70-74", "75+"],
}


def test_simulation_with_parameter_override(client):
    """Override transform: value is 0.15 inside the window, baseline 0.3 outside."""
    request = {
        "model": {
            "preset": "SIR",
            "parameters": {"transmission_rate": 0.3, "recovery_rate": 0.1},
        },
        "population": {
            "name": "United_States",
        },
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-03-01",
            "Nsim": 5,
        },
        "parameter_transforms": [
            {
                "target_parameter": "transmission_rate",
                "method": "override",
                "start_date": "2024-01-15",
                "end_date": "2024-01-30",
                "value": 0.15,
            }
        ],
        "output": {"include_parameters": True},
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text

    params = response.json()["results"]["parameters"]
    dates = params["dates"]
    series = next(iter(params["data"]["transmission_rate"].values()))
    in_window = [v for d, v in zip(dates, series) if "2024-01-15" <= d <= "2024-01-30"]
    out_of_window = [v for d, v in zip(dates, series) if d < "2024-01-15" or d > "2024-01-30"]

    # Overridden to 0.15 in the window, baseline 0.3 outside
    assert in_window == pytest.approx([0.15] * len(in_window), abs=1e-9)
    assert out_of_window == pytest.approx([0.3] * len(out_of_window), abs=1e-9)


def test_simulation_scale_transform(client):
    """Scale transform multiplies the parameter by `factor` inside the window."""
    baseline = 0.3
    request = {
        "model": {
            "preset": "SIR",
            "parameters": {"transmission_rate": baseline, "recovery_rate": 0.1},
        },
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-03-01",
            "Nsim": 3,
        },
        "parameter_transforms": [
            {
                "target_parameter": "transmission_rate",
                "method": "scale",
                "start_date": "2024-02-01",
                "end_date": "2024-02-15",
                "factor": 0.5,
            }
        ],
        "output": {"include_parameters": True},
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text

    params = response.json()["results"]["parameters"]
    dates = params["dates"]
    series = next(iter(params["data"]["transmission_rate"].values()))
    in_window = [v for d, v in zip(dates, series) if "2024-02-01" <= d <= "2024-02-15"]
    out_of_window = [v for d, v in zip(dates, series) if d < "2024-02-01" or d > "2024-02-15"]

    # In the window, values should be half the baseline
    assert in_window == pytest.approx([baseline * 0.5] * len(in_window), abs=1e-9)
    assert out_of_window == pytest.approx([baseline] * len(out_of_window), abs=1e-9)


def test_simulation_age_varying_plus_balcan(client):
    """Age-varying base parameter composes with balcan seasonality.

    Exercises the (N,) -> (T, N) path in apply_transform_to_parameter that
    upstream's seasonality builder does not handle. At `max_date` each age
    group's value equals its declared base; at `min_date` each is base * val_min.
    """
    expected_base = [0.35, 0.35, 0.30, 0.25, 0.20]
    request = {
        "model": {
            "preset": "SIR",
            "parameters": {"transmission_rate": expected_base},
        },
        "population": {
            "name": "United_States",
            "contacts_source": "prem_2021",
            "age_group_mapping": _AGE_GROUP_MAPPING_5,
        },
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-07-31",
            "Nsim": 3,
        },
        "parameter_transforms": [
            {
                "target_parameter": "transmission_rate",
                "method": "balcan",
                "max_date": "2024-01-15",
                "min_date": "2024-07-15",
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
    tx = params["data"]["transmission_rate"]
    groups = list(tx.keys())
    assert len(groups) == 5
    idx_max = dates.index("2024-01-15")
    idx_min = dates.index("2024-07-15")
    for group, base_val in zip(groups, expected_base):
        # At max_date: multiplier = 1.0, so value = base.
        assert tx[group][idx_max] == pytest.approx(base_val * 1.0, abs=1e-9), (
            f"{group}: value at max_date {tx[group][idx_max]} != base {base_val}"
        )
        # At min_date: multiplier = val_min, so value = base * val_min.
        assert tx[group][idx_min] == pytest.approx(base_val * 0.5, abs=1e-9), (
            f"{group}: value at min_date {tx[group][idx_min]} != base * 0.5 = {base_val * 0.5}"
        )


def test_simulation_override_age_varying_value(client):
    """Override with a per-age-group list value: each group gets its own override in-window."""
    override_values = [0.10, 0.12, 0.10, 0.08, 0.06]
    request = {
        "model": {"preset": "SIR"},
        "population": {
            "name": "United_States",
            "contacts_source": "prem_2021",
            "age_group_mapping": _AGE_GROUP_MAPPING_5,
        },
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-03-01",
            "Nsim": 3,
        },
        "parameter_transforms": [
            {
                "target_parameter": "transmission_rate",
                "method": "override",
                "start_date": "2024-02-01",
                "end_date": "2024-02-15",
                "value": override_values,  # Overrides the default transmission_rate values
            }
        ],
        "output": {"include_parameters": True},
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text

    params = response.json()["results"]["parameters"]
    dates = params["dates"]
    tx = params["data"]["transmission_rate"]
    groups = list(tx.keys())
    assert len(groups) == 5
    idx_in = dates.index("2024-02-10")
    for group, expected_val in zip(groups, override_values):
        assert tx[group][idx_in] == pytest.approx(expected_val, abs=1e-9), (
            f"{group}: in-window value {tx[group][idx_in]} != override {expected_val}"
        )


def _combined_request(transforms_in_order):
    return {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-03-01",
            "Nsim": 3,
            "seed": 42,
        },
        "parameter_transforms": transforms_in_order,
    }


def test_simulation_transforms_combined(client):
    """Balcan + scale + override compose layer by layer.

    - Outside scale/override windows: value = baseline * balcan_multiplier (seasonality only).
    - Inside scale window (outside override): value = baseline * balcan * scale_factor.
    - Inside override window: value = override_value (overrides both).
    """
    from app.utils.seasonality import calc_seasonality_balcan_at_date

    baseline = 0.3
    val_max, val_min = 1.0, 0.5
    scale_factor = 0.5
    override_value = 0.05

    request = _combined_request(
        [
            {
                "target_parameter": "transmission_rate",
                "method": "balcan",
                "max_date": "2024-01-15",
                "min_date": "2024-07-15",
                "max_value": val_max,
                "min_value": val_min,
            },
            {
                "target_parameter": "transmission_rate",
                "method": "scale",
                "start_date": "2024-02-01",
                "end_date": "2024-02-15",
                "factor": scale_factor,
            },
            {
                "target_parameter": "transmission_rate",
                "method": "override",
                "start_date": "2024-02-05",
                "end_date": "2024-02-10",
                "value": override_value,
            },
        ]
    )
    request["model"]["parameters"] = {"transmission_rate": baseline, "recovery_rate": 0.1}
    request["output"] = {"include_parameters": True}

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text

    params = response.json()["results"]["parameters"]
    dates = params["dates"]
    series = next(iter(params["data"]["transmission_rate"].values()))

    def balcan_at(date_str: str) -> float:
        return calc_seasonality_balcan_at_date(
            date_t=date_str,
            date_start="2024-01-01",
            date_tmax="2024-01-15",
            date_tmin="2024-07-15",
            val_min=val_min,
            val_max=val_max,
        )

    # 1. Seasonality only: Jan 15 is the balcan peak, no scale/override active.
    idx_jan_15 = dates.index("2024-01-15")
    assert series[idx_jan_15] == pytest.approx(baseline * 1.0, abs=1e-9)

    # 2. Balcan * scale: Feb 1 is inside the scale window, before the override window.
    idx_feb_1 = dates.index("2024-02-01")
    assert series[idx_feb_1] == pytest.approx(
        baseline * balcan_at("2024-02-01") * scale_factor, abs=1e-9
    )

    # 3. Override wins: Feb 7 is inside the override window.
    idx_feb_7 = dates.index("2024-02-07")
    assert series[idx_feb_7] == pytest.approx(override_value, abs=1e-9)


def test_simulation_transforms_order_independence_for_overrides(client):
    """Override wins for its window regardless of position in the transforms list."""
    override_value = 0.05
    multiplicative = [
        {
            "target_parameter": "transmission_rate",
            "method": "balcan",
            "max_date": "2024-01-15",
            "min_date": "2024-07-15",
            "max_value": 1.0,
            "min_value": 0.5,
        },
        {
            "target_parameter": "transmission_rate",
            "method": "scale",
            "start_date": "2024-02-01",
            "end_date": "2024-02-15",
            "factor": 0.5,
        },
    ]
    override = {
        "target_parameter": "transmission_rate",
        "method": "override",
        "start_date": "2024-02-05",
        "end_date": "2024-02-10",
        "value": override_value,
    }

    def _run(transforms):
        request = _combined_request(transforms)
        request["output"] = {"include_parameters": True}
        response = client.post("/api/v1/simulations", json=request)
        assert response.status_code == 200, response.text
        return response.json()["results"]

    results_a = _run(multiplicative + [override])
    results_b = _run([override] + multiplicative)

    # Parameter series agree under both orderings, AND the override value
    # actually appears in its window (rules out "lost in both orderings").
    series_a = next(iter(results_a["parameters"]["data"]["transmission_rate"].values()))
    series_b = next(iter(results_b["parameters"]["data"]["transmission_rate"].values()))
    assert series_a == pytest.approx(series_b, abs=1e-12)

    dates = results_a["parameters"]["dates"]
    in_override_a = [v for d, v in zip(dates, series_a) if "2024-02-05" <= d <= "2024-02-10"]
    assert in_override_a == pytest.approx([override_value] * len(in_override_a), abs=1e-9)


def test_simulation_transform_undefined_target_parameter(client):
    """An unknown target_parameter surfaces as a 422 with a clear message."""
    request = {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-15",
            "Nsim": 2,
        },
        "parameter_transforms": [
            {
                "target_parameter": "no_such_param",
                "method": "scale",
                "start_date": "2024-01-05",
                "end_date": "2024-01-10",
                "factor": 0.5,
            }
        ],
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422
    assert "no_such_param" in response.json()["detail"]


def test_simulation_transform_validation_error_missing_field(client):
    """A method-required field is checked by the discriminated union (422)."""
    request = {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-15",
            "Nsim": 2,
        },
        "parameter_transforms": [
            # method=balcan but missing max_date/max_value/min_value
            {"target_parameter": "transmission_rate", "method": "balcan"}
        ],
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422


def test_simulation_transform_invalid_window_scale(client):
    """`scale` rejects end_date < start_date with 422."""
    request = {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-15",
            "Nsim": 2,
        },
        "parameter_transforms": [
            {
                "target_parameter": "transmission_rate",
                "method": "scale",
                "start_date": "2024-02-15",
                "end_date": "2024-02-01",
                "factor": 0.5,
            }
        ],
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422


def test_simulation_transform_invalid_window_override(client):
    """`override` rejects end_date < start_date with 422."""
    request = {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-15",
            "Nsim": 2,
        },
        "parameter_transforms": [
            {
                "target_parameter": "transmission_rate",
                "method": "override",
                "start_date": "2024-02-15",
                "end_date": "2024-02-01",
                "value": 0.1,
            }
        ],
    }

    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 422


def test_simulation_include_parameters_off_by_default(client):
    """`output.include_parameters` defaults to false; `results.parameters` is null."""
    request = {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
            "Nsim": 2,
            "seed": 1,
        },
    }
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200
    assert response.json()["results"].get("parameters") is None


def test_simulation_include_parameters_emits_baked_in_overrides(client):
    """With include_parameters=true, the response shows transmission_rate dropping
    to the override value inside the override window and returning to baseline outside."""
    request = {
        "model": {
            "preset": "SIR",
            "parameters": {"transmission_rate": 0.3, "recovery_rate": 0.1},
        },
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "Nsim": 2,
            "seed": 1,
        },
        "parameter_transforms": [
            {
                "target_parameter": "transmission_rate",
                "method": "override",
                "start_date": "2024-01-10",
                "end_date": "2024-01-15",
                "value": 0.05,
            }
        ],
        "output": {"include_parameters": True},
    }
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200

    params = response.json()["results"]["parameters"]
    assert params is not None
    assert "transmission_rate" in params["data"]
    # Pick any age group; arrays are broadcast so all groups carry the same scalar.
    age_group = next(iter(params["data"]["transmission_rate"]))
    series = params["data"]["transmission_rate"][age_group]
    dates = params["dates"]

    # Outside the override window, value is the baseline 0.3.
    idx_jan_5 = dates.index("2024-01-05")
    assert series[idx_jan_5] == pytest.approx(0.3, abs=1e-9)

    # Inside [Jan 10, Jan 15], the override 0.05 is baked in.
    idx_jan_12 = dates.index("2024-01-12")
    assert series[idx_jan_12] == pytest.approx(0.05, abs=1e-9)

    # After the window, back to baseline.
    idx_jan_20 = dates.index("2024-01-20")
    assert series[idx_jan_20] == pytest.approx(0.3, abs=1e-9)


def test_simulation_metadata_echoes_transforms_and_interventions(client):
    """`SimulationMetadata` should echo back `parameter_transforms` and `interventions`."""
    request = {
        "model": {"preset": "SIR"},
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-15",
            "Nsim": 2,
            "seed": 1,
        },
        "interventions": [
            {
                "layer_name": "school",
                "start_date": "2024-01-05",
                "end_date": "2024-01-10",
                "reduction_factor": 0.3,
            }
        ],
        "parameter_transforms": [
            {
                "target_parameter": "transmission_rate",
                "method": "scale",
                "start_date": "2024-01-05",
                "end_date": "2024-01-10",
                "factor": 0.5,
            }
        ],
    }
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200

    metadata = response.json()["metadata"]
    assert metadata["interventions"] is not None
    assert metadata["interventions"][0]["layer_name"] == "school"
    assert metadata["parameter_transforms"] is not None
    assert metadata["parameter_transforms"][0]["method"] == "scale"


def test_simulation_transform_no_aliasing():
    """Two `scale` transforms on the same parameter must compose multiplicatively (not just last-write).

    Catches an aliasing regression where a later transform overwrites the prior
    step's stored array instead of multiplying into it.
    """
    from app.api.v1.schemas.simulation import (
        BuiltinPopulationConfig,
        ModelConfig,
        ScaleTransform,
        SimulationConfig,
    )
    from app.services.model_service import create_model
    from app.services.parameter_transforms_service import apply_parameter_transforms_sources
    from app.services.population_service import setup_population

    model, _, _ = create_model(ModelConfig(preset="SIR", parameters={"transmission_rate": 1.0}))
    setup_population(model, BuiltinPopulationConfig(name="United_States"))

    sim_cfg = SimulationConfig(start_date="2024-01-01", end_date="2024-01-10", Nsim=1)
    transforms = [
        ScaleTransform(
            target_parameter="transmission_rate",
            method="scale",
            start_date="2024-01-01",
            end_date="2024-01-10",
            factor=2.0,
        ),
        ScaleTransform(
            target_parameter="transmission_rate",
            method="scale",
            start_date="2024-01-01",
            end_date="2024-01-10",
            factor=3.0,
        ),
    ]
    apply_parameter_transforms_sources(model, list(transforms), sim_cfg)

    # Final stored value should be baseline * 2 * 3 = 6 across the window.
    final = model.get_parameter("transmission_rate")
    assert hasattr(final, "__len__")
    assert list(final) == pytest.approx([6.0] * len(final), abs=1e-9)


def test_summary_peak_date_matches_trajectory_argmax_with_transform(client):
    """`summary.peaks.<comp>.total.peak_date` matches the calendar date at argmax of
    the median trajectory, even when a parameter transform shifts the peak.

    Pins the wiring between the summary's `peak_date` field and the underlying
    compartments data: a regression that computed peak_date from the wrong array
    or off-by-one index would silently mislead callers.
    """
    import numpy as np

    request = {
        "model": {
            "preset": "SIR",
            "parameters": {"transmission_rate": 0.3, "recovery_rate": 0.1},
        },
        "population": {"name": "United_States"},
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-06-01",
            "Nsim": 10,
            "seed": 7,
        },
        "parameter_transforms": [
            {
                "target_parameter": "transmission_rate",
                "method": "scale",
                "start_date": "2024-01-15",
                "end_date": "2024-03-15",
                "factor": 0.7,
            }
        ],
    }
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    results = response.json()["results"]

    peak_date = results["summary"]["peaks"]["Infected"]["total"]["peak_date"]
    dates = results["compartments"]["dates"]
    median_traj = results["compartments"]["data"]["Infected"]["total"]["0.5"]
    expected_peak_date = dates[int(np.argmax(median_traj))]

    assert peak_date == expected_peak_date, (
        f"summary peak_date={peak_date} != argmax(median trajectory)={expected_peak_date}"
    )
