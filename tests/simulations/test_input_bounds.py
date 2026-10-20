"""Numeric bounds and references rejected with 422 before the simulation runs."""

import copy
import json

import pytest

ENDPOINTS = ["/api/v1/simulations", "/api/v1/simulations/export/python"]
INF = float("inf")

BASE = {
    "model": {"preset": "SEIR"},
    "population": {
        "source": "custom",
        "name": "two_groups",
        "age_groups": {"A": 10000, "B": 20000},
        "contact_matrices": {"all": [[8.0, 2.0], [1.0, 6.0]]},
    },
    "simulation": {"start_date": "2025-01-01", "end_date": "2025-01-31", "Nsim": 1, "seed": 7},
}
CUSTOM_MODEL = {
    "compartments": ["S", "I", "J"],
    "parameters": {"beta": 0.3},
    "transitions": [{"source": "S", "target": "I", "kind": "mediated", "params": ["beta", "I"]}],
}


def _request(**sections):
    request = copy.deepcopy(BASE)
    for key, value in sections.items():
        request[key] = {**request[key], **value} if key == "simulation" else value
    return request


def _post(client, endpoint, payload):
    # 1e400 is valid JSON that parses to infinity; httpx's json= refuses inf.
    body = json.dumps(payload).replace("Infinity", "1e400")
    return client.post(endpoint, content=body, headers={"Content-Type": "application/json"})


def _population(**fields):
    return {**BASE["population"], **fields}


def _absolute(**compartments):
    return {"method": "absolute", "compartments": compartments}


def _custom(*transitions):
    return {**CUSTOM_MODEL, "transitions": list(transitions)}


# Rejected by the request schema, so both endpoints agree.
SCHEMA_INVALID = {
    "percentage_negative": _request(initial_conditions={"initial_percentages": {"Infected": -1}}),
    "percentage_over_100": _request(initial_conditions={"initial_percentages": {"Infected": 101}}),
    "percentage_sum_over_100": _request(
        initial_conditions={"initial_percentages": {"Infected": 60, "Recovered": 60}}
    ),
    "percentage_infinite": _request(initial_conditions={"initial_percentages": {"Infected": INF}}),
    "absolute_empty": _request(initial_conditions=_absolute()),
    "absolute_negative": _request(
        initial_conditions=_absolute(Susceptible=[10010, 20010], Infected=[-10, -10])
    ),
    "absolute_short": _request(initial_conditions=_absolute(Susceptible=[9990], Infected=[10])),
    "absolute_long": _request(
        initial_conditions=_absolute(Susceptible=[9990, 19990, 10], Infected=[10, 10, 0])
    ),
    "population_negative": _request(population=_population(age_groups={"A": -10, "B": 20000})),
    "population_zero_group": _request(population=_population(age_groups={"A": 0, "B": 20000})),
    "contacts_negative": _request(
        population=_population(contact_matrices={"all": [[-8, 0], [0, -6]]})
    ),
    "contacts_infinite": _request(
        population=_population(contact_matrices={"all": [[INF, 2.0], [1.0, 6.0]]})
    ),
    "dt_infinite": _request(simulation={"dt": INF}),
    "frequency_garbage": _request(simulation={"resample_frequency": "garbage"}),
    "frequency_zero": _request(simulation={"resample_frequency": "0D"}),
    "frequency_negative": _request(simulation={"resample_frequency": "-1D"}),
    "frequency_removed_alias": _request(simulation={"resample_frequency": "M"}),
    "unknown_mediator": _request(
        model=_custom({"source": "S", "target": "I", "kind": "mediated", "params": ["beta", "X"]})
    ),
    "unknown_rate": _request(
        model=_custom({"source": "S", "target": "I", "kind": "mediated", "params": ["gamma", "I"]})
    ),
    "mediated_without_mediator": _request(
        model=_custom({"source": "S", "target": "I", "kind": "mediated", "params": ["beta"]})
    ),
    "intervention_unknown_layer": _request(
        interventions=[
            {
                "layer_name": "school",
                "start_date": "2025-01-05",
                "end_date": "2025-01-10",
                "reduction_factor": 0.5,
            }
        ]
    ),
    "intervention_layer_not_loaded": _request(
        population={"name": "United_States", "layers": ["home"]},
        interventions=[
            {
                "layer_name": "school",
                "start_date": "2025-01-05",
                "end_date": "2025-01-10",
                "reduction_factor": 0.5,
            }
        ],
    ),
    "period_negative": _request(model={"preset": "SEIR", "parameters": {"infectious_period": -2}}),
    "period_list_zero": _request(
        model={"preset": "SEIR", "parameters": {"incubation_period": [3.0, 0.0]}}
    ),
    "balcan_zero_max": _request(
        parameter_transforms=[
            {
                "method": "balcan",
                "target_parameter": "transmission_rate",
                "max_date": "2025-01-15",
                "min_value": 0.5,
                "max_value": 0,
            }
        ]
    ),
    "balcan_zero_period": _request(
        parameter_transforms=[
            {
                "method": "balcan",
                "target_parameter": "transmission_rate",
                "max_date": "2025-01-15",
                "min_date": "2025-01-15",
                "min_value": 0.5,
            }
        ]
    ),
}

# Only known once parameters are evaluated, transformed, or the population is loaded.
RESOLVED_INVALID = {
    "rate_negative": _request(model={"preset": "SEIR", "parameters": {"transmission_rate": -0.3}}),
    "rate_negative_expression": _request(
        model={"preset": "SEIR", "parameters": {"transmission_rate": "0 - 0.3"}}
    ),
    "rate_infinite": _request(model={"preset": "SEIR", "parameters": {"recovery_rate": INF}}),
    "rate_negative_after_scale": _request(
        parameter_transforms=[
            {
                "method": "scale",
                "target_parameter": "transmission_rate",
                "start_date": "2025-01-05",
                "end_date": "2025-01-10",
                "factor": -1,
            }
        ]
    ),
    "probability_below_0": _request(model={"preset": "V-SEIR", "parameters": {"VE_S": -0.1}}),
    "probability_above_1": _request(model={"preset": "V-SEIR", "parameters": {"VE_S": "1.1"}}),
    "builtin_absolute_length": _request(
        population={"name": "United_States__Vermont"},
        initial_conditions=_absolute(Susceptible=[1000, 1000], Infected=[1, 1]),
    ),
}

VALID = {
    "zero_contacts_with_beta": _request(
        model={"preset": "SEIR", "parameters": {"transmission_rate": 0.3}},
        population=_population(contact_matrices={"all": [[0, 0], [0, 0]]}),
    ),
    "rate_above_1": _request(model={"preset": "SEIR", "parameters": {"recovery_rate": 2.0}}),
    "negative_helper": _request(
        model={"preset": "SEIR", "parameters": {"offset": -0.1, "recovery_rate": "0.3 + offset"}}
    ),
    "percentages_sum_100": _request(
        initial_conditions={"initial_percentages": {"Infected": 1, "Recovered": 99}}
    ),
    "absolute_matching": _request(
        initial_conditions=_absolute(Susceptible=[9990, 19990], Infected=[10, 10])
    ),
    "weekly": _request(simulation={"resample_frequency": "W"}),
    "month_end": _request(simulation={"resample_frequency": "ME"}),
    "custom_model": _request(
        model=CUSTOM_MODEL, initial_conditions=_absolute(S=[9990, 19990], I=[10, 10])
    ),
}


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("case", SCHEMA_INVALID)
def test_schema_rejects_invalid_input(client, endpoint, case):
    response = _post(client, endpoint, SCHEMA_INVALID[case])
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("case", RESOLVED_INVALID)
def test_simulation_rejects_invalid_resolved_values(client, case):
    response = _post(client, "/api/v1/simulations", RESOLVED_INVALID[case])
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("endpoint", ENDPOINTS)
@pytest.mark.parametrize("case", VALID)
def test_valid_input_is_accepted(client, endpoint, case):
    response = _post(client, endpoint, VALID[case])
    assert response.status_code == 200, response.text


def test_rate_error_names_parameter(client):
    response = client.post("/api/v1/simulations", json=RESOLVED_INVALID["rate_negative"])
    assert "transmission_rate" in response.json()["detail"]
