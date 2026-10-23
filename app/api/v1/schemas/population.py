"""Population-related schema definitions.

This module defines Pydantic models for population data, contact matrices,
and model presets.
"""

from pydantic import BaseModel, Field


class PopulationSummary(BaseModel):
    """Summary information for a population."""

    name: str = Field(
        ..., description="Population identifier (e.g., 'United_States')", examples=["United_States"]
    )
    display_name: str = Field(..., description="Human-readable name", examples=["United States"])
    total_population: int | None = Field(
        default=None, description="Total population size", examples=[338120586]
    )
    available_contact_sources: list[str] = Field(
        default_factory=list,
        description="Available contact matrix sources",
        examples=[["prem_2017", "prem_2021", "mistry_2021"]],
    )


class PopulationListResponse(BaseModel):
    """Response for listing all available populations."""

    populations: list[PopulationSummary]
    total: int = Field(..., description="Total number of populations.", examples=[152])


class ContactMatrixInfo(BaseModel):
    """Information about a contact matrix."""

    layer: str = Field(..., description="Contact layer name")
    shape: list[int] = Field(..., description="Matrix dimensions [rows, cols]")
    mean_contacts: float = Field(..., description="Mean number of contacts")


class PopulationDetail(BaseModel):
    """Detailed information about a population."""

    name: str = Field(..., description="Population identifier.", examples=["United_States"])
    display_name: str = Field(..., description="Human-readable name.", examples=["United States"])
    total_population: int = Field(..., description="Total population size.", examples=[338120586])
    age_groups: dict[str, int] = Field(
        ...,
        description="Default 5-group aggregation (epydemix `mistry_2021`/`prem_2021` coarse groups). Keys are in age-ascending order.",
        examples=[
            {
                "0-4": 18608139,
                "5-19": 63540783,
                "20-49": 132780169,
                "50-64": 63172279,
                "65+": 60019216,
            }
        ],
    )
    age_distribution: dict[str, int] = Field(
        ...,
        description='Raw per-single-year population counts from the upstream `age_distribution.csv`. Keys are age labels (e.g. `"0"`..`"83"`, `"84+"`) in ascending order.',
        examples=[{"0": 18608139, "1": 18500000, "2": 18400000, "83": 900000, "84+": 3200000}],
    )
    contact_sources: list[str] = Field(
        ...,
        description="Available contact matrix sources.",
        examples=[["prem_2017", "prem_2021", "mistry_2021"]],
    )
    default_contact_source: str | None = Field(
        default=None,
        description="Default contact source for this population.",
        examples=["mistry_2021"],
    )
    available_layers: list[str] = Field(
        ...,
        description="Available contact layers (e.g. home, work, school, community).",
        examples=[["home", "work", "school", "community"]],
    )


class ContactMatrixResponse(BaseModel):
    """Response containing contact matrices for a population."""

    population_name: str = Field(
        ..., description="Population identifier.", examples=["United_States"]
    )
    contact_source: str = Field(
        ..., description="Contact matrix source used.", examples=["mistry_2021"]
    )
    layers: dict[str, list[list[float]]] = Field(
        ...,
        description="Contact matrices by layer name. Each matrix is square with one row/column per age group.",
        examples=[
            {
                "home": [[1.24, 0.87, 0.15], [0.91, 2.03, 0.34], [0.19, 0.42, 1.77]],
                "work": [[0.08, 0.41, 0.02], [0.54, 2.11, 0.17], [0.03, 0.23, 0.05]],
                "school": [[0.00, 0.00, 0.00], [0.00, 5.42, 0.00], [0.00, 0.00, 0.00]],
                "community": [[0.61, 0.88, 0.42], [0.94, 1.56, 0.67], [0.51, 0.72, 0.83]],
            }
        ],
    )
    overall: list[list[float]] | None = Field(
        default=None,
        description="Combined contact matrix across all layers.",
        examples=[[[1.93, 2.16, 0.59], [2.39, 11.12, 1.18], [0.73, 1.37, 2.65]]],
    )
    age_groups: list[str] = Field(
        ...,
        description="Age group labels for matrix indices (same order as rows and columns).",
        examples=[["0-19", "20-64", "65+"]],
    )
    spectral_radius: dict[str, float] = Field(
        default_factory=dict,
        description="Spectral radius (largest eigenvalue) for each layer and overall.",
        examples=[
            {
                "home": 2.41,
                "work": 2.28,
                "school": 5.42,
                "community": 2.64,
                "overall": 12.34,
            }
        ],
    )


class PresetInfo(BaseModel):
    """Information about a predefined epidemic model."""

    name: str = Field(..., description="Preset name (e.g., 'SIR', 'SEIR')", examples=["SIR"])
    description: str = Field(
        ...,
        description="Description of the model.",
        examples=["Susceptible-Infected-Recovered compartmental model."],
    )
    compartments: list[str] = Field(
        ...,
        description="Compartment names.",
        examples=[["Susceptible", "Infected", "Recovered"]],
    )
    parameters: dict[str, float | list[float]] = Field(
        ...,
        description=(
            "Default parameter values. A list value means the default is "
            "age-stratified (one entry per age group on the resolved population)."
        ),
        examples=[{"R0": 2.5, "recovery_rate": 0.1}],
    )
    transitions: list[dict] = Field(
        ...,
        description="Transition definitions.",
        examples=[
            [
                {
                    "source": "Susceptible",
                    "target": "Infected",
                    "kind": "mediated",
                    "params": ["transmission_rate", "Infected"],
                },
                {
                    "source": "Infected",
                    "target": "Recovered",
                    "kind": "spontaneous",
                    "params": ["recovery_rate"],
                },
            ]
        ],
    )


class PresetsListResponse(BaseModel):
    """Response listing all available model presets."""

    presets: list[PresetInfo]
