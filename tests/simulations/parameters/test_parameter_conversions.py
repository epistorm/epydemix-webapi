"""Preset parameter conversions and precedence."""

import pytest

from .helpers import _custom_sir_request, _preset_request


def test_sir_infectious_period_drives_recovery_rate(client):
    """`infectious_period: 7.0` on SIR injects `recovery_rate = 1/7` as a calc-param."""
    response = client.post(
        "/api/v1/simulations",
        json=_preset_request("SIR", {"infectious_period": 7.0, "transmission_rate": 0.3}),
    )
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]["data"]
    series = next(iter(params["recovery_rate"].values()))
    assert series == pytest.approx([1 / 7.0] * len(series), abs=1e-12)


def test_sir_period_inputs_match_explicit_rate(client):
    """Period-style and rate-style inputs produce identical trajectories with the same seed."""
    period_resp = client.post(
        "/api/v1/simulations",
        json=_preset_request("SIR", {"infectious_period": 7.0, "transmission_rate": 0.3}),
    )
    rate_resp = client.post(
        "/api/v1/simulations",
        json=_preset_request("SIR", {"recovery_rate": 1 / 7.0, "transmission_rate": 0.3}),
    )
    assert period_resp.status_code == rate_resp.status_code == 200

    period_infected = period_resp.json()["results"]["compartments"]["data"]["Infected"]
    rate_infected = rate_resp.json()["results"]["compartments"]["data"]["Infected"]
    # Same seed = identical trajectories across every age group and every quantile.
    assert period_infected == rate_infected


def test_sir_R0_drives_transmission_rate(client):
    """`R0: 2.5` injects `transmission_rate = R0 * recovery_rate / eig(C)`."""
    response = client.post(
        "/api/v1/simulations",
        json=_preset_request("SIR", {"R0": 2.5, "recovery_rate": 0.1}),
    )
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]["data"]
    series = next(iter(params["transmission_rate"].values()))
    # Non-zero, finite values; exact value depends on the contact-matrix eigenvalue.
    assert series[0] > 0
    assert series[0] == series[-1]  # scalar source, no time variation


_TWO_GROUP_POPULATION = {
    "source": "custom",
    "name": "TwoGroups",
    "age_groups": {"young": 50_000, "old": 50_000},
    "contact_matrices": {"all": [[2.0, 1.0], [1.0, 2.0]]},
}

_TWO_LAYER_POPULATION = {
    "source": "custom",
    "name": "TwoLayers",
    "age_groups": {"a": 30_000, "b": 50_000, "c": 20_000},
    "contact_matrices": {
        "home": [[3.0, 1.0, 0.5], [1.0, 2.0, 0.2], [0.5, 0.2, 1.0]],
        "work": [[0.5, 2.0, 0.0], [2.0, 6.0, 0.1], [0.0, 0.1, 0.3]],
    },
}


def _calculate_dominant_eigenvalue(population: dict) -> float:
    import numpy as np

    summed = sum(np.asarray(m, dtype=float) for m in population["contact_matrices"].values())
    return float(np.max(np.abs(np.linalg.eigvals(summed))))


def _get_effective_rates(client, preset: str, population: dict, parameters: dict) -> dict:
    request = _preset_request(preset, parameters)
    request["population"] = population
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed", body.get("error")
    parameter_data = body["results"]["parameters"]["data"]
    return {name: next(iter(series.values()))[0] for name, series in parameter_data.items()}


@pytest.mark.parametrize("preset", ["SIR", "SEIR", "SIS"])
@pytest.mark.parametrize("population", [_TWO_GROUP_POPULATION, _TWO_LAYER_POPULATION])
def test_basic_preset_defaults_give_R0_2_5(client, preset, population):
    """With no parameters, the derived beta gives R0 = beta * rho(C) / mu = 2.5 on any matrix."""
    rates = _get_effective_rates(client, preset, population, {})
    eigenvalue = _calculate_dominant_eigenvalue(population)
    assert rates["recovery_rate"] == pytest.approx(0.1, abs=1e-12)
    # transmission_rate = R0 * recovery_rate / eigenvalue.
    assert rates["transmission_rate"] == pytest.approx(2.5 * 0.1 / eigenvalue, rel=1e-9)
    # R0 = transmission_rate * eigenvalue / recovery_rate.
    effective_R0 = rates["transmission_rate"] * eigenvalue / rates["recovery_rate"]
    assert effective_R0 == pytest.approx(2.5, rel=1e-9)
    if preset == "SEIR":
        assert rates["incubation_rate"] == pytest.approx(0.2, abs=1e-12)


@pytest.mark.parametrize("preset", ["SIR", "SEIR", "SIS"])
def test_basic_preset_explicit_transmission_rate_wins_over_default_R0(client, preset):
    """An explicit `transmission_rate` stands as given; the default `R0` is dropped."""
    rates = _get_effective_rates(client, preset, _TWO_LAYER_POPULATION, {"transmission_rate": 0.3})
    assert rates["transmission_rate"] == pytest.approx(0.3, abs=1e-12)
    assert "R0" not in rates


@pytest.mark.parametrize("preset", ["SIR", "SEIR", "SIS"])
def test_basic_preset_explicit_R0_and_infectious_period(client, preset):
    """User `R0` and `infectious_period` replace the defaults in the beta conversion."""
    population = _TWO_LAYER_POPULATION
    eigenvalue = _calculate_dominant_eigenvalue(population)

    rates = _get_effective_rates(client, preset, population, {"R0": 1.5})
    # 0.1 is the default recovery_rate for the SIR, SEIR, and SIS presets.
    # transmission_rate = R0 * recovery_rate / eigenvalue.
    assert rates["transmission_rate"] == pytest.approx(1.5 * 0.1 / eigenvalue, rel=1e-9)

    rates = _get_effective_rates(client, preset, population, {"infectious_period": 5.0})
    # recovery_rate = 1 / infectious_period = 1 / 5.0 = 0.2.
    assert rates["recovery_rate"] == pytest.approx(0.2, abs=1e-12)
    # 2.5 is the default R0 for the SIR, SEIR, and SIS presets.
    # transmission_rate = R0 * recovery_rate / eigenvalue.
    assert rates["transmission_rate"] == pytest.approx(2.5 * 0.2 / eigenvalue, rel=1e-9)


def test_both_passed_derived_wins(client):
    """Passing both `infectious_period` and `recovery_rate`: the derived (rate) wins."""
    response = client.post(
        "/api/v1/simulations",
        json=_preset_request(
            "SIR", {"infectious_period": 7.0, "recovery_rate": 0.5, "transmission_rate": 0.3}
        ),
    )
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]["data"]
    series = next(iter(params["recovery_rate"].values()))
    # User scalar `recovery_rate: 0.5` should stand, not the conversion `1/7`.
    assert series == pytest.approx([0.5] * len(series), abs=1e-12)
    # `infectious_period` source scalar should have been popped from model.parameters.
    assert "infectious_period" not in params


def test_custom_model_no_implicit_period_conversion(client):
    """Custom models opt out of period-to-rate conversion.

    Even with `infectious_period` supplied, no `recovery_rate` calc-param
    is injected: the conversion is preset-scoped.
    `infectious_period` is just an unused parameter name; nothing implicit happens.
    """
    request = _custom_sir_request(
        {
            "infectious_period": 7.0,  # This is would not be converted to recovery rate in a custom model. Remains unused.
            "transmission_rate": 0.3,
            "recovery_rate": 0.1,  # supplied explicitly
        }
    )
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]["data"]

    # User scalar wins; the conversion is opted out in custom model, so `recovery_rate` stays at 0.1.
    series = next(iter(params["recovery_rate"].values()))
    assert series == pytest.approx([0.1] * len(series), abs=1e-12)

    # `infectious_period` is present but unused: NOT consumed by any conversion.
    assert "infectious_period" in params


def test_custom_model_explicit_period_to_rate_calc_param(client):
    """Custom models can opt INTO the period-to-rate conversion explicitly.

    Complement of `test_custom_model_no_implicit_period_conversion`: the
    preset-scoped resolver doesn't fire for custom models, but a user can
    write the same expression as a calc-param. The general calc-param
    machinery evaluates it regardless of preset.
    """
    request = _custom_sir_request(
        {
            "infectious_period": 7.0,
            "transmission_rate": 0.3,
            "recovery_rate": "1 / infectious_period",  # explicit user calc-param
        }
    )
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    params = response.json()["results"]["parameters"]["data"]
    series = next(iter(params["recovery_rate"].values()))
    assert series == pytest.approx([1 / 7.0] * len(series), abs=1e-12)
