"""Render population, contact, and preset resources as executable Python."""

from __future__ import annotations

from ...api.v1.schemas.simulation import CustomPopulationConfig
from ...presets import PRESETS
from ..population_service import DEFAULT_LAYERS
from .expression_renderer import _literal, _render_transition


def render_population_list_python(attribute: str = "age", level: int | None = None) -> str:
    """Render a script that lists epydemix population locations.

    Parameters
    ----------
    attribute : str, optional
        Population attribute used to filter available locations.
    level : int or None, optional
        Geographic level passed to epydemix.

    Returns
    -------
    str
        Executable Python source that prints the matching locations.
    """
    return f'''from epydemix.population import get_available_locations

locations = get_available_locations(
    attribute={attribute!r},
    data_version="v1.2.0",
    level={level!r},
)

print(locations)
'''


def render_population_python(name: str, contacts_source: str | None = None) -> str:
    """Render a script that loads and summarizes an epydemix population.

    Parameters
    ----------
    name : str
        epydemix population identifier.
    contacts_source : str or None, optional
        Contact-matrix data source.

    Returns
    -------
    str
        Executable Python source that prints population metadata.
    """
    return f'''from epydemix.population import load_epydemix_population

population = load_epydemix_population(
    population_name={name!r},
    contacts_source={contacts_source!r},
    layers={DEFAULT_LAYERS!r},
    data_version="v1.2.0",
)

print("Name:", population.name)
print("Total population:", population.total_population)
print("Age groups:", population.Nk_names)
print("Population by age group:", population.Nk)
print("Contact layers:", population.layers)
'''


def render_contacts_python(
    name: str,
    contacts_source: str | None = None,
    layers: list[str] | None = None,
) -> str:
    """Render a script that inspects contact matrices and spectral radii.

    Parameters
    ----------
    name : str
        epydemix population identifier.
    contacts_source : str or None, optional
        Contact-matrix data source.
    layers : list of str or None, optional
        Contact layers to load. Uses the API defaults when omitted.

    Returns
    -------
    str
        Executable Python source that prints each matrix and its spectral radius.
    """
    selected_layers = layers or DEFAULT_LAYERS
    return f'''import numpy as np

from epydemix.population import load_epydemix_population


def calculate_spectral_radius(matrix) -> float:
    """Return the largest absolute eigenvalue of a contact matrix."""
    eigenvalues = np.linalg.eigvals(np.asarray(matrix, dtype=float))
    return float(np.max(np.abs(eigenvalues)))


population = load_epydemix_population(
    population_name={name!r},
    contacts_source={contacts_source!r},
    layers={selected_layers!r},
    data_version="v1.2.0",
)

for layer, matrix in population.contact_matrices.items():
    print(f"{{layer}}:")
    print(matrix)
    print("Spectral radius:", calculate_spectral_radius(matrix))

overall = sum(
    np.asarray(matrix, dtype=float)
    for matrix in population.contact_matrices.values()
)
print("Overall:")
print(overall)
print("Overall spectral radius:", calculate_spectral_radius(overall))
'''


def render_custom_population_python(config: CustomPopulationConfig) -> str:
    """Render Python commands that construct a custom population.

    Age-group and contact-layer insertion order is preserved so the generated
    population has the same group indices and matrices as the API request.

    Parameters
    ----------
    config : CustomPopulationConfig
        Validated custom population definition from the API request.

    Returns
    -------
    str
        Executable Python source that assigns the population to ``population``.
    """
    lines = [
        "import numpy as np",
        "",
        "from epydemix.population import Population",
        "",
        f"population = Population(name={config.name!r})",
        "population.add_population(",
        f"    Nk={_literal([float(value) for value in config.age_groups.values()])},",
        f"    Nk_names={_literal(list(config.age_groups))},",
        ")",
    ]
    for layer, matrix in config.contact_matrices.items():
        lines.extend(
            [
                "population.add_contact_matrix(",
                f"    contact_matrix=np.array({_literal(matrix)}, dtype=float),",
                f"    layer_name={layer!r},",
                ")",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def render_preset_python(name: str) -> str:
    """Render Python commands that construct a registered model preset.

    Population-dependent parameter conversions are intentionally deferred until
    a population is attached; the full simulation exporter emits those calls.

    Parameters
    ----------
    name : str
        Name of a preset in the local preset registry.

    Returns
    -------
    str
        Executable Python source that assigns the preset model to ``model``.

    Raises
    ------
    KeyError
        If ``name`` is not present in the preset registry.
    """
    definition = PRESETS[name]
    lines = [
        "import numpy as np",
        "",
        "from epydemix import EpiModel",
        "",
        f"model = EpiModel(name={name!r}, compartments={_literal(definition.compartments)})",
    ]
    for parameter, value in definition.default_parameters.items():
        native_value = (
            f"np.array({_literal(value)}, dtype=float).reshape(1, -1)"
            if isinstance(value, list)
            else repr(value)
        )
        lines.append(
            f"model.add_parameter(parameter_name={parameter!r}, value={native_value})"
        )
    for transition in definition.transitions:
        lines.extend(
            [
                "",
                *_render_transition(
                    transition["source"],
                    transition["target"],
                    transition["kind"],
                    list(transition["params"]),
                ),
            ]
        )
    if definition.parameter_conversions:
        lines.extend(
            [
                "",
                "# Population-dependent parameters such as transmission_rate are calculated",
                "# after a population is attached; the simulation exporter emits those commands.",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
