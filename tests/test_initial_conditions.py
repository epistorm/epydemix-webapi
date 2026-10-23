"""Unit tests for ``create_initial_conditions`` in isolation.

Builds a minimal ``EpiModel`` with a real ``Population`` and calls the helper
directly so we can pin down the ``percentage`` / ``absolute`` branches, the
remainder-into-first-compartment fallback, and the preset-default hook
without spinning up the full simulation pipeline.
"""

import numpy as np
import pytest
from epydemix.model.epimodel import EpiModel
from epydemix.population.population import Population

from app.api.v1.schemas.simulation import InitialConditionsConfig
from app.services.model_service import create_initial_conditions


def _model(Nk: list[float] | None = None) -> EpiModel:
    """SIR model. One age group of 1000 by default; pass `Nk` for multi-group."""
    sizes = Nk if Nk is not None else [1000.0]
    model = EpiModel(compartments=["Susceptible", "Infected", "Recovered"])
    pop = Population(name="test")
    names = [f"g{i}" for i in range(len(sizes))]
    pop.add_population(Nk=sizes, Nk_names=names)
    n = len(sizes)
    pop.add_contact_matrix(contact_matrix=np.ones((n, n)), layer_name="all")
    model.set_population(pop)
    return model


def test_returns_none_when_no_config_and_no_preset_default():
    """Returns None so epydemix's `create_default_initial_conditions` is used downstream."""
    model = _model()
    assert create_initial_conditions(model, config=None) is None
    assert callable(model.create_default_initial_conditions)


def test_preset_default_invoked_when_config_is_none():
    """When `config` is None, the preset-supplied builder is called with the model."""
    model = _model(Nk=[500.0])
    expected_default = {"Susceptible": np.array([499.0]), "Infected": np.array([1.0])}
    called_with: list[EpiModel] = []

    def preset_default(m: EpiModel) -> dict[str, np.ndarray]:
        called_with.append(m)
        return expected_default

    result = create_initial_conditions(model, config=None, preset_default=preset_default)
    assert result is expected_default
    assert called_with == [model]


def test_preset_default_skipped_when_caller_supplies_config():
    """Caller-provided config wins over the preset default."""
    model = _model()
    config = InitialConditionsConfig(
        method="absolute", compartments={"Infected": [10.0]}
    )

    def preset_default(_: EpiModel) -> dict[str, np.ndarray]:
        raise AssertionError("preset_default should not be called when config is provided")

    result = create_initial_conditions(model, config=config, preset_default=preset_default)
    assert set(result) == {"Infected"}
    assert result["Infected"].tolist() == [10.0]


def test_absolute_method_uses_counts_verbatim():
    """`absolute` returns the requested counts unchanged, as np.ndarrays."""
    config = InitialConditionsConfig(
        method="absolute",
        compartments={"Susceptible": [900.0, 800.0], "Infected": [100.0, 200.0]},
    )
    result = create_initial_conditions(_model(Nk=[1000.0, 1000.0]), config=config)
    assert set(result) == {"Susceptible", "Infected"}
    assert result["Susceptible"].tolist() == [900.0, 800.0]
    assert result["Infected"].tolist() == [100.0, 200.0]
    assert all(isinstance(v, np.ndarray) for v in result.values())


def test_percentage_method_seeds_remainder_into_first_compartment():
    """`percentage` puts requested fractions into named comps; remainder -> first comp."""
    # initial_percentages are in *percent* (0-100), not fraction.
    config = InitialConditionsConfig(
        method="percentage", initial_percentages={"Infected": 1.0, "Recovered": 10.0}
    )
    result = create_initial_conditions(_model(Nk=[1000.0]), config=config)
    # 1% of 1000 = 10, 10% of 1000 = 100, remainder = 890 into Susceptible.
    assert result["Infected"] == pytest.approx([10.0])
    assert result["Recovered"] == pytest.approx([100.0])
    assert result["Susceptible"] == pytest.approx([890.0])


def test_percentage_method_preserves_age_group_shape():
    """Percentages apply per age group; counts vary across groups."""
    config = InitialConditionsConfig(
        method="percentage", initial_percentages={"Infected": 5.0}
    )
    result = create_initial_conditions(_model(Nk=[1000.0, 4000.0]), config=config)
    assert result["Infected"] == pytest.approx([50.0, 200.0])
    assert result["Susceptible"] == pytest.approx([950.0, 3800.0])


def test_percentage_method_first_compartment_explicit_adds_remainder():
    """If the first compartment is explicitly listed, the remainder is *added* to it."""
    # 1% Susceptible + 1% Infected = 2% total specified; remainder 98% adds to Susceptible.
    config = InitialConditionsConfig(
        method="percentage",
        initial_percentages={"Susceptible": 1.0, "Infected": 1.0},
    )
    result = create_initial_conditions(_model(Nk=[1000.0]), config=config)
    # Susceptible: 10 (explicit) + 980 (remainder) = 990; Infected: 10.
    assert result["Susceptible"] == pytest.approx([990.0])
    assert result["Infected"] == pytest.approx([10.0])
    # Total preserved.
    assert sum(v.sum() for v in result.values()) == pytest.approx(1000.0)


def test_absolute_without_compartments_rejected_at_schema_level():
    """Schema validation rejects `absolute` without `compartments`."""
    with pytest.raises(ValueError, match="'compartments' must be provided"):
        InitialConditionsConfig(method="absolute")


# TODO: add coverage initial conditions where it is split between E and I