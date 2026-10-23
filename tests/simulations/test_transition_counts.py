"""Recorded transition counts with several mediated transitions sharing source and target.

Regression for the duplicated counting fixed in epydemix 1.3.0
(https://github.com/epistorm/epydemix/issues/25).
"""

import pytest

POPULATION = {
    "source": "custom",
    "name": "two_groups",
    "age_groups": {"young": 500_000, "old": 500_000},
    "contact_matrices": {"all": [[5.0, 2.0], [2.0, 5.0]]},
}
SIMULATION = {"start_date": "2025-01-01", "end_date": "2025-03-01", "Nsim": 1, "seed": 3}


def _total(series):
    return series["total"]["0.5"]


def _run(client, request):
    response = client.post("/api/v1/simulations", json=request)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "completed", data
    return data["results"]


def _custom_request(extra_transitions):
    return {
        "model": {
            "compartments": ["S", "E", "I", "J"],
            "parameters": {"beta": 0.1, "sigma": 0.2},
            "transitions": [
                {"source": "S", "target": "E", "kind": "mediated", "params": ["beta", "I"]},
                {"source": "E", "target": "I", "kind": "spontaneous", "params": "sigma"},
                *extra_transitions,
            ],
        },
        "population": POPULATION,
        "simulation": SIMULATION,
        "initial_conditions": {
            "method": "absolute",
            "compartments": {"S": [499_900, 499_900], "I": [100, 100]},
        },
    }


def test_zero_mediator_does_not_change_counts(client):
    """A second S->E transition mediated by an empty compartment changes nothing."""
    one = _run(client, _custom_request([]))
    two = _run(
        client,
        _custom_request(
            [{"source": "S", "target": "E", "kind": "mediated", "params": ["beta", "J"]}]
        ),
    )

    assert two["compartments"]["data"] == one["compartments"]["data"]
    assert two["transitions"]["data"] == one["transitions"]["data"]
    assert sum(_total(one["transitions"]["data"]["S_to_E"])) > 0


@pytest.mark.parametrize("preset", ["V-SEIR", "V-SEIHR"])
def test_vaccination_model_susceptible_balance(client, preset):
    """Susceptible decrease matches recorded infections over the same dates.

    The first reported day is already after one update, so the transitions
    recorded on it are excluded from the comparison.
    """
    results = _run(
        client,
        {
            "model": {"preset": preset},
            "population": {"name": "United_States__Vermont"},
            "simulation": SIMULATION,
        },
    )
    susceptible = _total(results["compartments"]["data"]["Susceptible"])
    transitions = results["transitions"]["data"]
    infections = sum(_total(transitions["Susceptible_to_Exposed"])[1:])
    waned = sum(_total(transitions["Recovered_to_Susceptible"])[1:])

    assert infections > 0
    assert susceptible[0] - susceptible[-1] == infections - waned
