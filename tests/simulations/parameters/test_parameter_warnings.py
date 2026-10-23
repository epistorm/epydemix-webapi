"""Warnings for ignored preset conversion inputs."""

import pytest

from .helpers import _custom_sir_request, _preset_request


@pytest.mark.parametrize(
    "preset, parameters, expected",
    [
        (
            "SEIR",
            {"infectious_period": 7.0, "recovery_rate": 0.2},
            [{"parameter": "infectious_period", "overridden_by": "recovery_rate"}],
        ),
        (
            "SEIR",
            {"R0": 2.0, "transmission_rate": 0.3},
            [{"parameter": "R0", "overridden_by": "transmission_rate"}],
        ),
        (
            "SEIR",
            {"incubation_period": 3.0, "incubation_rate": 0.5},
            [{"parameter": "incubation_period", "overridden_by": "incubation_rate"}],
        ),
        (
            "SIR",
            {"R0": "2 * 1.25", "transmission_rate": 0.3},
            [{"parameter": "R0", "overridden_by": "transmission_rate"}],
        ),
        (
            "V-SEIR",
            {"immunity_duration": 365.0, "waning_rate": 0.01},
            [{"parameter": "immunity_duration", "overridden_by": "waning_rate"}],
        ),
        (
            "V-SEIHR",
            {
                "R0": 1.8,
                "transmission_rate": 0.05,
                "hosp_duration": 5.0,
                "hosp_recovery_rate": 0.25,
            },
            [
                {"parameter": "hosp_duration", "overridden_by": "hosp_recovery_rate"},
                {"parameter": "R0", "overridden_by": "transmission_rate"},
            ],
        ),
        # Derived as an expression that does not use the source.
        (
            "SEIR",
            {"recovery_rate": "0.2", "infectious_period": 7.0},
            [{"parameter": "infectious_period", "overridden_by": "recovery_rate"}],
        ),
        (
            "SEIR",
            {"recovery_rate": "0.2", "infectious_period": "3 + 4"},
            [{"parameter": "infectious_period", "overridden_by": "recovery_rate"}],
        ),
        (
            "SIR",
            {"transmission_rate": "0.1 * recovery_rate", "R0": 2.0, "infectious_period": 7.0},
            [{"parameter": "R0", "overridden_by": "transmission_rate"}],
        ),
        (
            "V-SEIHR",
            {"recovery_rate": "0.4", "infectious_period": 2.5},
            [{"parameter": "infectious_period", "overridden_by": "recovery_rate"}],
        ),
    ],
)
def test_parameter_overridden_warning(client, preset, parameters, expected):
    """Supplying both a conversion source and its derived rate warns which one was ignored."""
    response = client.post("/api/v1/simulations", json=_preset_request(preset, parameters))
    assert response.status_code == 200, response.text
    warnings = response.json()["warnings"]
    actual = [{"parameter": w["parameter"], "overridden_by": w["overridden_by"]} for w in warnings]
    assert sorted(actual, key=lambda w: w["parameter"]) == sorted(
        expected, key=lambda w: w["parameter"]
    )
    for w in warnings:
        assert w["code"] == "parameter_overridden"
        assert w["message"] == (
            f"{w['parameter']} was ignored because {w['overridden_by']} was explicitly provided."
        )


# Each (preset, parameters) case below should return warnings: [].
# User-supplied sources are still used, or only preset defaults are overridden.
@pytest.mark.parametrize(
    "preset, parameters",
    [
        ("SIR", {"transmission_rate": 0.3}),
        ("SEIR", {"R0": 2.5, "recovery_rate": 0.1}),
        ("SIR", {"infectious_period": 7.0, "recovery_rate": "1 / infectious_period"}),
        (
            "SEIR",
            {"recovery_rate": "gamma", "gamma": "1 / infectious_period", "infectious_period": 7.0},
        ),
        (
            "V-SEIR",  # The explicit transmission_rate expression uses R0.
            {
                # transmission_rate = R0 * recovery_rate / eigenvalue.
                "transmission_rate": "R0 * recovery_rate / CONTACT_MATRIX_EIGENVALUE_ALL",
                # Vaccination halves the unvaccinated transmission rate with VE_S = 0.5.
                "transmission_rate_vax": "transmission_rate * (1 - VE_S)",
                "R0": 2.0,
                "VE_S": 0.5,
            },
        ),
        ("V-SEIR", {"recovery_rate": "0.4"}),  # source only from preset defaults
        ("V-SEIR", {}),  # preset defaults include R0 and infectious_period
        ("V-SEIR", {"transmission_rate": 0.05, "recovery_rate": 0.4}),  # overrides defaults only
    ],
)
def test_no_warning_without_user_conflict(client, preset, parameters):
    """Rate-only inputs, source-only inputs, and preset defaults produce an empty list."""
    request = _preset_request(preset, parameters)
    del request["output"]  # warnings do not depend on include_parameters
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    assert response.json()["warnings"] == []


def test_overridden_source_does_not_change_results(client):
    """Adding the ignored sources leaves the trajectories identical for the same seed."""
    rates = {"transmission_rate": 0.3, "recovery_rate": 0.2}
    plain = client.post("/api/v1/simulations", json=_preset_request("SEIR", rates))
    conflicting = client.post(
        "/api/v1/simulations",
        json=_preset_request("SEIR", {**rates, "R0": 5.0, "infectious_period": 3.0}),
    )
    assert plain.status_code == conflicting.status_code == 200
    assert plain.json()["warnings"] == []
    assert len(conflicting.json()["warnings"]) == 2
    for key in ("compartments", "transitions"):
        assert conflicting.json()["results"][key] == plain.json()["results"][key]


def test_custom_model_has_no_warnings(client):
    """Custom models have no conversions, so period and rate together do not warn."""
    request = _custom_sir_request(
        {"infectious_period": 7.0, "transmission_rate": 0.3, "recovery_rate": 0.1}
    )
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    assert response.json()["warnings"] == []


def test_source_ignored_by_derived_expression_does_not_change_results(client):
    """A source that the derived expression does not use leaves the trajectories unchanged."""
    params = {"transmission_rate": 0.3, "recovery_rate": "0.2"}
    plain = client.post("/api/v1/simulations", json=_preset_request("SEIR", params))
    conflicting = client.post(
        "/api/v1/simulations",
        json=_preset_request("SEIR", {**params, "infectious_period": 3.0}),
    )
    assert plain.status_code == conflicting.status_code == 200
    assert plain.json()["warnings"] == []
    assert [w["parameter"] for w in conflicting.json()["warnings"]] == ["infectious_period"]
    for key in ("compartments", "transitions"):
        assert conflicting.json()["results"][key] == plain.json()["results"][key]
