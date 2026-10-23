"""Simulation response schemas: trajectory results, summary, metadata, and the top-level response."""

from typing import Literal

from pydantic import BaseModel, Field

from .request import InterventionConfig, VaccinationConfig
from .transforms import ParameterTransformConfig

PopulationSource = Literal["builtin", "custom"]


class CompartmentResults(BaseModel):
    """Compartment trajectory quantiles."""

    dates: list[str] = Field(
        ...,
        description="Dates corresponding to values; ISO timestamps are used for subdaily samples.",
        examples=[["2024-01-01", "2024-01-02", "2024-01-03"]],
    )
    data: dict[str, dict[str, dict[str, list[float]]]] = Field(
        ...,
        description="Nested structure: `compartment -> age_group -> quantile -> [values]`.",
        examples=[
            {
                "Susceptible": {
                    "total": {
                        "0.025": [337330089.45, 334285584.7, 331100000.2],
                        "0.5": [337330136.0, 334286966.0, 331103421.0],
                        "0.975": [337330182.55, 334288347.3, 331106841.8],
                    },
                },
                "Infected": {
                    "total": {
                        "0.025": [621344.45, 3041835.25, 5800000.0],
                        "0.5": [621391.0, 3043170.0, 5812500.0],
                        "0.975": [621437.55, 3044504.75, 5825000.0],
                    },
                },
            }
        ],
    )


class TransitionResults(BaseModel):
    """Transition count quantiles."""

    dates: list[str] = Field(
        ...,
        description="Dates corresponding to values; ISO timestamps are used for subdaily samples.",
        examples=[["2024-01-01", "2024-01-02", "2024-01-03"]],
    )
    data: dict[str, dict[str, dict[str, list[float]]]] = Field(
        ...,
        description="Nested structure: `transition -> age_group -> quantile -> [values]`.",
        examples=[
            {
                "Susceptible_to_Infected": {
                    "total": {
                        "0.025": [621344.45, 3041835.25, 5800000.0],
                        "0.5": [621391.0, 3043170.0, 5812500.0],
                        "0.975": [621437.55, 3044504.75, 5825000.0],
                    },
                },
            }
        ],
    )


class StatisticQuantiles(BaseModel):
    """Quantile values for a summary statistic, keyed by quantile string (e.g. `0.5`)."""

    quantiles: dict[str, float] = Field(
        ...,
        description='Quantile to value mapping, e.g. `{"0.025": ..., "0.5": ..., "0.975": ...}`.',
        examples=[{"0.025": 213000000.0, "0.5": 215000000.0, "0.975": 217000000.0}],
    )


class PeakStatistic(BaseModel):
    """Peak statistic for a compartment in one age group."""

    quantiles: dict[str, float] = Field(
        ...,
        description='Peak value per quantile, e.g. `{"0.025": ..., "0.5": ..., "0.975": ...}`.',
        examples=[{"0.025": 12200000.0, "0.5": 12400000.0, "0.975": 12600000.0}],
    )
    peak_date: str | None = Field(
        default=None,
        description="Date of the peak from the median trajectory.",
        examples=["2024-02-14"],
    )


class SummaryResults(BaseModel):
    """Summary statistics of the simulation."""

    peaks: dict[str, dict[str, PeakStatistic]] | None = Field(
        default=None,
        description="Peak statistics: `compartment -> age_group -> {quantiles, peak_date}`.",
        examples=[
            {
                "Infected": {
                    "total": {
                        "quantiles": {"0.025": 12200000.0, "0.5": 12400000.0, "0.975": 12600000.0},
                        "peak_date": "2024-02-14",
                    },
                    "0-4": {
                        "quantiles": {"0.025": 410000.0, "0.5": 420000.0, "0.975": 435000.0},
                        "peak_date": "2024-02-13",
                    },
                },
            }
        ],
    )
    totals: dict[str, dict[str, StatisticQuantiles]] | None = Field(
        default=None,
        description="Cumulative transition totals: `transition -> age_group -> {quantiles}`.",
        examples=[
            {
                "Susceptible_to_Infected": {
                    "total": {
                        "quantiles": {
                            "0.025": 213000000.0,
                            "0.5": 215000000.0,
                            "0.975": 217000000.0,
                        }
                    },
                    "0-4": {
                        "quantiles": {"0.025": 11700000.0, "0.5": 11800000.0, "0.975": 11900000.0}
                    },
                },
            }
        ],
    )


class TrajectoryData(BaseModel):
    """Raw trajectory data for a single simulation run."""

    compartments: dict[str, dict[str, list[float]]] = Field(
        ...,
        description="Compartment values: `{compartment: {age_group: [values]}}`.",
        examples=[
            {
                "Susceptible": {"total": [337330136.0, 334286966.0, 331103421.0]},
                "Infected": {"total": [621391.0, 3043170.0, 5812500.0]},
                "Recovered": {"total": [0.0, 20000.0, 145000.0]},
            }
        ],
    )
    transitions: dict[str, dict[str, list[float]]] = Field(
        ...,
        description="Transition counts: `{transition: {age_group: [values]}}`.",
        examples=[
            {
                "Susceptible_to_Infected": {"total": [621391.0, 3043170.0, 5812500.0]},
                "Infected_to_Recovered": {"total": [0.0, 20000.0, 145000.0]},
            }
        ],
    )


class TrajectoriesResults(BaseModel):
    """Raw trajectories from all simulation runs."""

    dates: list[str] = Field(
        ...,
        description="Dates corresponding to values; ISO timestamps are used for subdaily samples.",
        examples=[["2024-01-01", "2024-01-02", "2024-01-03"]],
    )
    runs: list[TrajectoryData] = Field(..., description="Data for each simulation run.")


class ParameterResults(BaseModel):
    """Effective parameter values used during the simulation, broadcast to per-step
    arrays. Useful for plotting `transmission_rate` vs. time after seasonality, scaling,
    or override transforms have been applied. Only present if `include_parameters` was true.
    """

    dates: list[str] = Field(
        ...,
        description="Dates matching the internal grid, with ISO timestamps for subdaily samples.",
        examples=[["2024-01-01", "2024-01-02", "2024-01-03"]],
    )
    data: dict[str, dict[str, list[float]]] = Field(
        ...,
        description=(
            "Nested structure: `parameter_name -> age_group -> [values per date]`. "
            "Scalar parameters and time-varying scalars are broadcast across all age groups; "
            "age-varying parameters report each group separately. Override windows are baked "
            "into the returned arrays so they reflect what actually drove the simulation."
        ),
        examples=[
            {
                "transmission_rate": {
                    "0-4": [0.300, 0.299, 0.298],
                    "5-17": [0.300, 0.299, 0.298],
                },
                "recovery_rate": {
                    "0-4": [0.10, 0.10, 0.10],
                    "5-17": [0.10, 0.10, 0.10],
                },
            }
        ],
    )


class SimulationResultsData(BaseModel):
    """All simulation results."""

    compartments: CompartmentResults
    transitions: TransitionResults
    summary: SummaryResults | None = None
    trajectories: TrajectoriesResults | None = Field(
        default=None,
        description="Raw trajectory data. Only present if `include_trajectories` was true.",
    )
    parameters: ParameterResults | None = Field(
        default=None,
        description="Effective per-step parameter arrays. Only present if `include_parameters` was true.",
    )


class ModelMetadata(BaseModel):
    """Model section of simulation metadata. Mirrors the `model` section of the request."""

    preset: str | None = Field(
        default=None, description="Preset name if a preset was used.", examples=["SIR"]
    )
    compartments: list[str] = Field(
        ...,
        description="Compartment names in the model.",
        examples=[["Susceptible", "Infected", "Recovered"]],
    )


class PopulationMetadata(BaseModel):
    """Population section of simulation metadata. Mirrors the `population` section of the request and adds resolved/derived values."""

    source: PopulationSource = Field(
        default="builtin",
        description=(
            "Which population branch the request resolved to. `builtin` = loaded "
            "from the epydemix data repo; `custom` = supplied inline."
        ),
        examples=["builtin"],
    )
    name: str = Field(..., description="Population identifier.", examples=["United_States"])
    contacts_source: str | None = Field(
        default=None,
        description="Resolved contact matrix source actually used. `null` for custom populations.",
        examples=["mistry_2021"],
    )
    layers: list[str] | None = Field(
        default=None,
        description="Resolved contact layers actually used.",
        examples=[["home", "work", "school", "community"]],
    )
    age_group_mapping: dict[str, list[str]] | None = Field(
        default=None,
        description="Custom age group aggregation, echoed back if the request supplied one. `null` for custom populations.",
        examples=[{"0-19": ["0-4", "5-9", "10-14", "15-19"], "20+": ["20-24", "25-29", "30-34"]}],
    )
    total: int = Field(..., description="Total population size.", examples=[338120586])
    age_groups: dict[str, int] = Field(
        ...,
        description='Age group label to population count, e.g. `{"0-4": 18608139}`. Keys are in model (age-ascending) order.',
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
    contact_matrices: dict[str, list[list[float]]] = Field(
        default_factory=dict,
        description=(
            "Per-layer contact matrices actually used by the simulation, keyed by layer name. "
            "Row/column order matches `age_groups` insertion order."
        ),
        examples=[{"all": [[1.0]]}],
    )


class SimulationRunMetadata(BaseModel):
    """Simulation section of metadata. Mirrors the `simulation` section of the request."""

    start_date: str = Field(..., description="Simulation start date.", examples=["2024-01-01"])
    end_date: str = Field(..., description="Simulation end date.", examples=["2024-06-01"])
    Nsim: int = Field(..., description="Number of simulation runs.", examples=[10])
    dt: float = Field(..., description="Time step in days.", examples=[1.0])
    seed: int | None = Field(default=None, description="Random seed used.", examples=[42])
    resample_frequency: str = Field(..., description="Resampling frequency.", examples=["D"])


class SimulationMetadata(BaseModel):
    """Metadata about the simulation run, grouped to mirror the request shape."""

    model: ModelMetadata = Field(..., description="Model configuration used for the run.")
    population: PopulationMetadata = Field(
        ..., description="Resolved population configuration and derived counts."
    )
    simulation: SimulationRunMetadata = Field(
        ..., description="Simulation execution parameters used for the run."
    )
    interventions: list[InterventionConfig] | None = Field(
        default=None,
        description="Contact-reduction interventions applied to the run, echoed from the request.",
    )
    parameter_transforms: list[ParameterTransformConfig] | None = Field(
        default=None,
        description="Parameter transforms applied to the run, echoed from the request.",
    )
    vaccination: VaccinationConfig | None = Field(
        default=None,
        description="Vaccination configuration applied to the run, echoed from the request.",
    )


class SimulationWarning(BaseModel):
    """Non-fatal notice about how the request was interpreted. Never changes the results."""

    code: Literal["parameter_overridden"] = Field(
        ...,
        description=(
            "Machine-readable warning code. `parameter_overridden`: a preset conversion "
            "source (e.g. `infectious_period`, `R0`) was ignored because the rate it "
            "converts to was explicitly provided."
        ),
        examples=["parameter_overridden"],
    )
    parameter: str = Field(
        ..., description="Parameter that was ignored.", examples=["infectious_period"]
    )
    overridden_by: str = Field(
        ..., description="Parameter that took precedence.", examples=["recovery_rate"]
    )
    message: str = Field(
        ...,
        description="Human-readable explanation. Use `code` for programmatic checks.",
        examples=["infectious_period was ignored because recovery_rate was explicitly provided."],
    )


class SimulationResponse(BaseModel):
    """Complete simulation response."""

    simulation_id: str = Field(
        ...,
        description="Unique identifier for this simulation run.",
        examples=["sim_c9617343b215"],
    )
    status: Literal["completed"] = Field(
        ...,
        description=(
            "Always `completed`. Failed runs return an HTTP error instead: 422 for "
            "invalid input, 504 for a population load timeout, 500 for an internal error."
        ),
        examples=["completed"],
    )
    metadata: SimulationMetadata = Field(..., description="Metadata about the simulation run.")
    results: SimulationResultsData = Field(..., description="Simulation results.")
    warnings: list[SimulationWarning] = Field(
        default_factory=list,
        description="Non-fatal warnings about the request. Empty when there are none.",
    )
