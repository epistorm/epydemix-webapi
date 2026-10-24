"""Regressions for standalone export safety and API parameter semantics."""

from __future__ import annotations

import ast
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from epydemix.utils.utils import compute_simulation_dates

from app.api.v1.schemas.simulation import SimulationRequest
from app.presets import PRESETS
from app.services.model_service import (
    apply_age_varying_parameters,
    apply_calculated_parameters,
    create_model,
)
from app.services.population_service import setup_population
from app.services.python_export.script_helpers import _TRANSFORM_HELPERS
from app.utils.parameter_conversions import resolve_parameter_conversions
from app.utils.parameter_transforms import window_mask_for_dates
from tests.test_python_exports import (
    SIMPLE_SIMULATION,
    _assert_csv_matches_api,
    _assert_python_response,
)


def _execute_export(client, request, tmp_path, monkeypatch):
    source = _assert_python_response(
        client.post("/api/v1/simulations/export/python", json=request)
    )
    monkeypatch.chdir(tmp_path)
    namespace = {}
    exec(compile(source, "<export>", "exec"), namespace)
    return namespace, source


def _assert_export_matches_response(namespace, response):
    assert response.status_code == 200, response.text
    body = response.json()
    for section, key in (("compartments", "compartment_quantiles"), ("transitions", "transition_quantiles")):
        native = namespace[key].copy()
        native["date"] = native["date"].dt.strftime("%Y-%m-%d")
        _assert_csv_matches_api(native, body["results"][section])


@pytest.mark.parametrize("parameter_type", ["expression", "transformed"])
def test_dynamic_parameter_names_cannot_inject_python(
    parameter_type, client, tmp_path, monkeypatch
):
    request = deepcopy(SIMPLE_SIMULATION)
    name = "helper\nreview_marker = True\n#"
    request["model"]["parameters"][name] = "1" if parameter_type == "expression" else 1
    if parameter_type == "transformed":
        request["parameter_transforms"] = [{
            "method": "override", "target_parameter": name, "value": 2,
            "start_date": "2025-01-02", "end_date": "2025-01-02",
        }]
    namespace, source = _execute_export(client, request, tmp_path, monkeypatch)
    assert "review_marker" not in namespace
    assert not any(
        isinstance(node, ast.Name) and node.id == "review_marker"
        for node in ast.walk(ast.parse(source))
    )
    assert name in namespace["model"].parameters


@pytest.mark.parametrize("preset", ["SIR", "V-SEIR"])
@pytest.mark.parametrize("initial", [None, {}, {"initial_percentages": {}}, {"initial_percentages": {"Infected": 0}}])
def test_empty_initial_conditions_use_defaults_but_explicit_zero_is_preserved(
    preset, initial, client, tmp_path, monkeypatch
):
    request = deepcopy(SIMPLE_SIMULATION)
    request["model"] = {"preset": preset}
    request["population"]["age_groups"] = {"all": 100000}
    if initial is not None:
        request["initial_conditions"] = initial
    namespace, _ = _execute_export(client, request, tmp_path, monkeypatch)
    _assert_export_matches_response(namespace, client.post("/api/v1/simulations", json=request))
    infected = namespace["compartment_quantiles"]["Infected_total"]
    if initial and initial.get("initial_percentages"):
        assert (infected == 0).all()
    else:
        assert (infected > 0).any()


@pytest.mark.parametrize("period", [5, "5", "duration * 2"])
def test_expression_periods_are_conversion_sources(period, client, tmp_path, monkeypatch):
    request = deepcopy(SIMPLE_SIMULATION)
    request["model"]["parameters"] = {
        "infectious_period": period, "duration": 2.5,
    }
    parsed = SimulationRequest.model_validate(request)
    model, lists, expressions = create_model(parsed.model)
    setup_population(model, parsed.population)
    apply_age_varying_parameters(model, lists)
    converted, overridden = resolve_parameter_conversions(
        model.parameters, {"infectious_period", "duration"} if period == 5 else {"duration"},
        PRESETS["SIR"].parameter_conversions, set(expressions),
    )
    apply_calculated_parameters(model, {**converted, **expressions})
    assert not overridden
    assert model.parameters["recovery_rate"] == pytest.approx(0.2)
    assert model.parameters["transmission_rate"] == pytest.approx(0.5)

    namespace, _ = _execute_export(client, request, tmp_path, monkeypatch)
    reference = deepcopy(request)
    reference["model"]["parameters"]["infectious_period"] = 5
    _assert_export_matches_response(namespace, client.post("/api/v1/simulations", json=reference))
    assert namespace["model"].parameters["recovery_rate"] == pytest.approx(0.2)


def test_explicit_rate_still_wins_over_expression_period(client, tmp_path, monkeypatch):
    request = deepcopy(SIMPLE_SIMULATION)
    request["model"]["parameters"]["infectious_period"] = "5"
    namespace, _ = _execute_export(client, request, tmp_path, monkeypatch)
    _assert_export_matches_response(namespace, client.post("/api/v1/simulations", json=request))
    assert namespace["model"].parameters["recovery_rate"] == 0.1


@pytest.mark.parametrize("dt", [0.5, 0.25])
def test_export_helpers_include_entire_end_day(dt):
    namespace = {"np": np, "compute_simulation_dates": compute_simulation_dates}
    exec(_TRANSFORM_HELPERS, namespace)
    dates = compute_simulation_dates("2025-01-01", "2025-01-04", dt=dt)
    active = window_mask_for_dates("2025-01-02", "2025-01-02", dates)
    assert active.sum() == int(1 / dt)
    override = namespace["apply_parameter_override"](
        1, 3, "2025-01-01", "2025-01-04", "2025-01-02", "2025-01-02", 1, dt,
    )
    scaling = namespace["apply_parameter_scaling"](
        1, "2025-01-01", "2025-01-04", "2025-01-02", "2025-01-02", 3, dt,
    )
    np.testing.assert_array_equal(override[:, 0], np.where(active, 3, 1))
    np.testing.assert_array_equal(scaling, np.where(active, 3, 1))


@pytest.mark.parametrize("dt", [0.5, 0.25])
def test_subdaily_campaign_and_override_match_api(dt, client, tmp_path, monkeypatch):
    request = deepcopy(SIMPLE_SIMULATION)
    request["model"] = {"preset": "V-SEIR", "parameters": {"transmission_rate": 0.3}}
    request["population"]["age_groups"] = {"all": 100000}
    request["simulation"].update(dt=dt, Nsim=3)
    request["parameter_transforms"] = [{
        "method": "override", "target_parameter": "transmission_rate", "value": 0,
        "start_date": "2025-01-02", "end_date": "2025-01-02",
    }]
    request["vaccination"] = {"campaigns": [
        {"start_date": "2025-01-02", "end_date": "2025-01-02",
         "rollout": {"type": "fixed_rate", "rate": 0.1}},
        {"start_date": "2025-01-01", "end_date": "2025-01-02",
         "rollout": {"type": "flat_count", "daily_doses": 100}},
    ]}
    namespace, _ = _execute_export(client, request, tmp_path, monkeypatch)
    _assert_export_matches_response(namespace, client.post("/api/v1/simulations", json=request))


@pytest.mark.parametrize("dt", [1, 0.5])
@pytest.mark.parametrize("frequency", ["W", "ME"])
def test_export_resampling_keeps_partial_period_counts(dt, frequency, client, tmp_path, monkeypatch):
    request = deepcopy(SIMPLE_SIMULATION)
    request["simulation"].update(dt=dt, end_date="2025-01-10")
    daily, _ = _execute_export(client, request, tmp_path, monkeypatch)
    request["simulation"]["resample_frequency"] = frequency
    aggregated, _ = _execute_export(client, request, tmp_path, monkeypatch)
    daily_run = daily["results"].trajectories[0]
    aggregated_run = aggregated["results"].trajectories[0]
    assert len(aggregated_run.dates) > 0
    for name, values in daily_run.transitions.items():
        assert sum(aggregated_run.transitions[name]) == sum(values)
    for name, values in daily_run.compartments.items():
        assert aggregated_run.compartments[name][-1] == values[-1]
    assert pd.Timestamp(aggregated_run.dates[-1]) >= pd.Timestamp(request["simulation"]["end_date"])


@pytest.mark.parametrize("expression", ["5", "duration * 2"])
def test_api_expression_conversion_matches_numeric_source(expression, client, tmp_path, monkeypatch):
    request = deepcopy(SIMPLE_SIMULATION)
    request["model"]["parameters"] = {"infectious_period": expression, "duration": 2.5}
    request["output"] = {"include_parameters": True}
    expression_response = client.post("/api/v1/simulations", json=request)
    assert expression_response.status_code == 200, expression_response.text
    body = expression_response.json()
    assert body["results"]["parameters"]["data"]["recovery_rate"]["all"] == [0.2] * 3
    reference = deepcopy(request)
    reference["model"]["parameters"]["infectious_period"] = 5
    numeric_response = client.post("/api/v1/simulations", json=reference)
    assert numeric_response.status_code == 200, numeric_response.text
    for section in ("compartments", "transitions"):
        assert body["results"][section] == numeric_response.json()["results"][section]
    namespace, _ = _execute_export(client, request, tmp_path, monkeypatch)
    _assert_export_matches_response(namespace, expression_response)


def test_export_large_integer_literals_match_api_float_arithmetic(client, tmp_path, monkeypatch):
    request = deepcopy(SIMPLE_SIMULATION)
    request["model"]["parameters"]["recovery_rate"] = "9007199254740993 - 9007199254740992"
    request["output"] = {"include_parameters": True}
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    assert response.json()["results"]["parameters"]["data"]["recovery_rate"]["all"] == [0] * 3
    namespace, _ = _execute_export(client, request, tmp_path, monkeypatch)
    assert namespace["model"].parameters["recovery_rate"] == 0
    _assert_export_matches_response(namespace, response)


def test_export_power_literals_use_bounded_float_operations(client):
    from app.services.python_export.expression_renderer import _render_expression

    expression = "2 ** (2 ** 100)"
    rendered = _render_expression(expression)
    literals = [node.value for node in ast.walk(ast.parse(rendered)) if isinstance(node, ast.Constant)]
    assert literals and all(isinstance(value, float) for value in literals)
    with pytest.raises(OverflowError):
        eval(rendered, {"__builtins__": {}})

    request = deepcopy(SIMPLE_SIMULATION)
    request["model"]["parameters"]["recovery_rate"] = expression
    assert client.post("/api/v1/simulations", json=request).status_code == 422


@pytest.mark.parametrize("expression", ["'2'", "1e400", "9" * 400])
def test_export_rejects_nonnumeric_or_nonfinite_literals(expression, client):
    request = deepcopy(SIMPLE_SIMULATION)
    request["model"]["parameters"]["recovery_rate"] = expression
    response = client.post("/api/v1/simulations/export/python", json=request)
    assert response.status_code == 422
    assert "numeric" in response.text
