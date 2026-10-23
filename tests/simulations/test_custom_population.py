"""Custom-population path through the simulation endpoint and schema validators."""

CUSTOM_POPULATION_REQUEST = {
    "model": {
        "preset": "SIR",
        "parameters": {"transmission_rate": 0.3, "recovery_rate": 0.1},
    },
    "population": {
        "source": "custom",
        "name": "Toy population",
        "age_groups": {"A": 100, "B": 100},
        "contact_matrices": {"all": [[0.2, 0.3], [0.3, 0.2]]},
    },
    "simulation": {
        "start_date": "2024-01-01",
        "end_date": "2024-01-31",
        "Nsim": 5,
    },
}


def test_run_simulation_with_custom_population(client):
    """End-to-end: a custom 2-group population runs and metadata reflects the request."""
    response = client.post("/api/v1/simulations", json=CUSTOM_POPULATION_REQUEST)
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["status"] == "completed"

    pop_meta = data["metadata"]["population"]
    assert pop_meta["source"] == "custom"
    assert pop_meta["name"] == "Toy population"
    assert pop_meta["layers"] == ["all"]
    assert pop_meta["age_groups"] == {"A": 100, "B": 100}
    assert pop_meta["total"] == 200
    assert pop_meta["contacts_source"] is None
    assert pop_meta["age_group_mapping"] is None
    assert pop_meta["contact_matrices"] == {"all": [[0.2, 0.3], [0.3, 0.2]]}

    # Both age-group keys appear in the trajectory data.
    susceptible = data["results"]["compartments"]["data"]["Susceptible"]
    assert "A" in susceptible
    assert "B" in susceptible


def test_custom_population_default_name(client):
    """Omitting `name` falls back to `"Custom Population"`."""
    payload = {
        **CUSTOM_POPULATION_REQUEST,
        "population": {
            "source": "custom",
            "age_groups": {"A": 100, "B": 100},
            "contact_matrices": {"all": [[0.2, 0.3], [0.3, 0.2]]},
        },
    }
    response = client.post("/api/v1/simulations", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["metadata"]["population"]["name"] == "Custom Population"


def test_custom_population_multiple_layers_preserve_order(client):
    """`contact_matrices` key order defines the metadata `layers` order."""
    payload = {
        **CUSTOM_POPULATION_REQUEST,
        "population": {
            "source": "custom",
            "name": "multi-layer",
            "age_groups": {"A": 100, "B": 100},
            "contact_matrices": {
                "home": [[0.10, 0.05], [0.05, 0.10]],
                "work": [[0.15, 0.20], [0.20, 0.15]],
                "school": [[0.05, 0.05], [0.05, 0.05]],
            },
        },
    }
    response = client.post("/api/v1/simulations", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["metadata"]["population"]["layers"] == ["home", "work", "school"]


def test_custom_population_intervention_against_custom_layer(client):
    """Interventions can target a layer the user declared in `contact_matrices`."""
    payload = {
        **CUSTOM_POPULATION_REQUEST,
        "population": {
            "source": "custom",
            "name": "with intervention",
            "age_groups": {"A": 100, "B": 100},
            "contact_matrices": {
                "home": [[0.10, 0.05], [0.05, 0.10]],
                "work": [[0.15, 0.20], [0.20, 0.15]],
            },
        },
        "interventions": [
            {
                "layer_name": "work",
                "start_date": "2024-01-10",
                "end_date": "2024-01-20",
                "reduction_factor": 0.5,
                "name": "lockdown",
            }
        ],
    }
    response = client.post("/api/v1/simulations", json=payload)
    assert response.status_code == 200, response.text
    interventions = response.json()["metadata"]["interventions"]
    assert interventions and interventions[0]["layer_name"] == "work"


def test_custom_population_empty_age_groups_rejected(client):
    """Empty `age_groups` is a 422."""
    payload = {
        **CUSTOM_POPULATION_REQUEST,
        "population": {
            "source": "custom",
            "age_groups": {},
            "contact_matrices": {"all": [[0.2]]},
        },
    }
    response = client.post("/api/v1/simulations", json=payload)
    assert response.status_code == 422
    assert "age_groups" in response.text


def test_custom_population_empty_contact_matrices_rejected(client):
    """Empty `contact_matrices` is a 422."""
    payload = {
        **CUSTOM_POPULATION_REQUEST,
        "population": {
            "source": "custom",
            "age_groups": {"A": 100},
            "contact_matrices": {},
        },
    }
    response = client.post("/api/v1/simulations", json=payload)
    assert response.status_code == 422
    assert "contact_matrices" in response.text


def test_custom_population_dim_mismatch_rejected(client):
    """A matrix whose row count != len(age_groups) is a 422."""
    payload = {
        **CUSTOM_POPULATION_REQUEST,
        "population": {
            "source": "custom",
            "age_groups": {"A": 100, "B": 100, "C": 100},  # 3 groups
            "contact_matrices": {"all": [[0.2, 0.3], [0.3, 0.2]]},  # 2x2
        },
    }
    response = client.post("/api/v1/simulations", json=payload)
    assert response.status_code == 422


def test_custom_population_non_square_matrix_rejected(client):
    """A non-square matrix is a 422."""
    payload = {
        **CUSTOM_POPULATION_REQUEST,
        "population": {
            "source": "custom",
            "age_groups": {"A": 100, "B": 100},
            "contact_matrices": {"all": [[0.2, 0.3, 0.1], [0.3, 0.2, 0.1]]},  # 2x3
        },
    }
    response = client.post("/api/v1/simulations", json=payload)
    assert response.status_code == 422


def test_custom_population_reserved_layer_name_rejected(client):
    """Layer name `"overall"` is reserved by epydemix and rejected at request time."""
    payload = {
        **CUSTOM_POPULATION_REQUEST,
        "population": {
            "source": "custom",
            "age_groups": {"A": 100, "B": 100},
            "contact_matrices": {"overall": [[0.2, 0.3], [0.3, 0.2]]},
        },
    }
    response = client.post("/api/v1/simulations", json=payload)
    assert response.status_code == 422
    assert "overall" in response.text


def test_legacy_payload_without_source_field_still_works(client):
    """Existing `{"population": {"name": "United_States"}}` payloads keep working."""
    payload = {
        "model": {
            "preset": "SIR",
            "parameters": {"transmission_rate": 0.3, "recovery_rate": 0.1},
        },
        "population": {"name": "United_States"},  # no `source` field
        "simulation": {
            "start_date": "2024-01-01",
            "end_date": "2024-01-15",
            "Nsim": 3,
        },
    }
    response = client.post("/api/v1/simulations", json=payload)
    assert response.status_code == 200, response.text
    pop_meta = response.json()["metadata"]["population"]
    assert pop_meta["source"] == "builtin"
    assert pop_meta["name"] == "United_States"
    # Builtin path resolves contacts_source.
    assert pop_meta["contacts_source"] is not None
    # Builtin path also fills contact_matrices from the loaded population.
    assert pop_meta["contact_matrices"], "expected at least one contact-matrix layer"


def test_simulation_request_routes_to_custom_branch():
    """Direct schema instantiation: discriminator routes payload to CustomPopulationConfig."""
    from app.api.v1.schemas.simulation import CustomPopulationConfig, SimulationRequest

    req = SimulationRequest.model_validate(CUSTOM_POPULATION_REQUEST)
    assert isinstance(req.population, CustomPopulationConfig)
    assert req.population.source == "custom"
    assert list(req.population.age_groups.keys()) == ["A", "B"]


