"""Input budgets and arithmetic limits reject expensive work before allocation."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.api.v1.schemas.simulation import SimulationRequest
from app.config import settings
from app.utils.calculated_parameters import evaluate_expressions

BASE = {
    "model": {"preset": "SIR"},
    "population": {
        "source": "custom",
        "age_groups": {"A": 1000},
        "contact_matrices": {"all": [[1]]},
    },
    "simulation": {"start_date": "2024-01-01", "end_date": "2024-01-03", "Nsim": 1},
}


@pytest.mark.parametrize(
    "simulation",
    [
        {"dt": 1e-8},
        {"dt": 5e-324},
        {"end_date": "9999-12-31"},
        {"resample_frequency": "ns"},
    ],
)
def test_rejects_expensive_timelines(simulation):
    payload = deepcopy(BASE)
    payload["simulation"].update(simulation)
    with pytest.raises(ValidationError):
        SimulationRequest.model_validate(payload)


def test_runtime_nsim_setting_is_enforced(monkeypatch):
    monkeypatch.setattr(settings, "max_nsim", 1)
    payload = deepcopy(BASE)
    payload["simulation"]["Nsim"] = 2
    with pytest.raises(ValidationError, match="configured maximum"):
        SimulationRequest.model_validate(payload)


def test_contact_and_trajectory_budgets(monkeypatch):
    monkeypatch.setattr(settings, "max_contact_cells", 2)
    with pytest.raises(ValidationError, match="contact-matrix"):
        SimulationRequest.model_validate(BASE)
    monkeypatch.setattr(settings, "max_contact_cells", 100)
    monkeypatch.setattr(settings, "max_simulation_cells", 2)
    with pytest.raises(ValidationError, match="trajectory/parameter"):
        SimulationRequest.model_validate(BASE)


@pytest.mark.parametrize(
    "expr", ["2 ** (2 ** 100)", "1 / 0", "(-1) ** 0.5", "1e300 * 1e300", "1+" * 2000 + "1"]
)
def test_expression_work_and_results_are_bounded(expr):
    with pytest.raises(ValueError):
        evaluate_expressions({"rate": expr}, {})


def test_integer_sources_cannot_trigger_unbounded_python_power():
    with pytest.raises(ValueError):
        evaluate_expressions({"rate": "base ** power"}, {"base": 2, "power": 10**20})


@pytest.mark.parametrize("frequency", ["bh", "cbh", "2bh", "2cbh"])
def test_business_hour_offsets_cannot_bypass_output_step_budget(monkeypatch, frequency):
    monkeypatch.setattr(settings, "max_simulation_steps", 4)
    payload = deepcopy(BASE)
    payload["simulation"].update(
        start_date="2025-01-06", end_date="2025-01-08", resample_frequency=frequency,
    )
    with pytest.raises(ValidationError, match="Business-hour"):
        SimulationRequest.model_validate(payload)


@pytest.mark.parametrize("frequency", ["D", "B", "C", "W", "ME"])
def test_calendar_offsets_remain_supported(monkeypatch, frequency):
    monkeypatch.setattr(settings, "max_simulation_steps", 4)
    payload = deepcopy(BASE)
    payload["simulation"]["resample_frequency"] = frequency
    SimulationRequest.model_validate(payload)


@pytest.mark.parametrize("quantiles", [[], [-0.1], [1.1], [float("nan")], [float("inf")], [0.5] * 101])
@pytest.mark.parametrize("endpoint", ["/api/v1/simulations", "/api/v1/simulations/export/python"])
def test_invalid_quantiles_are_rejected_before_execution(client, monkeypatch, quantiles, endpoint):
    import json

    from app.api.v1.endpoints import simulations

    def unexpected_execution(*args, **kwargs):
        raise AssertionError("Invalid quantiles reached execution")

    monkeypatch.setattr(simulations, "run_simulation", unexpected_execution)
    monkeypatch.setattr(simulations, "render_simulation_python", unexpected_execution)
    payload = deepcopy(BASE)
    payload["output"] = {"quantiles": quantiles}
    response = client.post(endpoint, content=json.dumps(payload), headers={"Content-Type": "application/json"})
    assert response.status_code == 422, response.text
