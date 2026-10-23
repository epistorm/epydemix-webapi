"""Render simulation requests as standalone epydemix programs."""

from __future__ import annotations

from ...api.v1.schemas.simulation import CustomPopulationConfig, SimulationRequest
from ...presets import PRESETS
from ...utils.calculated_parameters import RESERVED_NAMES
from ..population_service import DEFAULT_LAYERS
from .expression_renderer import (
    _expression_order,
    _literal,
    _render_expression,
    _render_transform_calls,
    _render_transition,
    _validate_expressions,
)
from .script_helpers import (
    _CALCULATION_HELPERS,
    _PARAMETER_HELPERS,
    _TRANSFORM_HELPERS,
    _VACCINATION_HELPER,
)


def render_simulation_python(request: SimulationRequest) -> str:
    """Render a simulation request as a standalone epydemix script.

    The generated program constructs the requested population and model,
    applies parameter calculations and transforms, runs the simulation, and
    writes compartment and transition quantiles to CSV files.

    Parameters
    ----------
    request : SimulationRequest
        Validated API simulation request to reproduce locally.

    Returns
    -------
    str
        Executable Python source that imports epydemix directly.

    Raises
    ------
    ValueError
        If parameter expressions, names, or transforms are invalid.
    """
    raw_parameters = request.model.parameters or {}
    preset = PRESETS[request.model.preset] if request.model.preset else None
    needs_eigenvalue = False

    reserved_collisions = set(raw_parameters) & set(RESERVED_NAMES)
    if reserved_collisions:
        raise ValueError(
            "Parameter names collide with reserved names: "
            + ", ".join(sorted(reserved_collisions))
        )

    scalar_parameters: dict[str, float] = {}
    list_parameters: dict[str, list[float]] = {}
    expressions: dict[str, str] = {}

    if preset is not None:
        scalar_parameters.update(
            {
                name: float(value)
                for name, value in preset.default_parameters.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
        )
        list_parameters.update(
            {
                name: value
                for name, value in preset.default_parameters.items()
                if isinstance(value, list) and name not in raw_parameters
            }
        )
        # The registry builder returns preset-specific calculated parameters.
        _, preset_expressions = preset.build_model({})
        expressions.update(preset_expressions)

    scalar_parameters.update(
        {
            name: float(value)
            for name, value in raw_parameters.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
    )
    list_parameters.update(
        {name: value for name, value in raw_parameters.items() if isinstance(value, list)}
    )
    expressions.update(
        {name: value for name, value in raw_parameters.items() if isinstance(value, str)}
    )

    parameters_to_delete: list[str] = []
    if preset is not None:
        active_names = set(scalar_parameters) | set(list_parameters)
        user_non_expression = {
            name for name, value in raw_parameters.items() if not isinstance(value, str)
        }
        converted: dict[str, str] = {}
        for derived_name, conversion in preset.parameter_conversions.items():
            if derived_name in user_non_expression:
                if conversion.source in active_names:
                    parameters_to_delete.append(conversion.source)
                    active_names.discard(conversion.source)
                continue
            if conversion.source in active_names:
                converted[derived_name] = conversion.expression
        expressions = {**converted, **expressions}

    needs_eigenvalue = any(
        "CONTACT_MATRIX_EIGENVALUE_ALL" in expression for expression in expressions.values()
    )
    resolved_parameter_names = (
        (set(scalar_parameters) | set(list_parameters)) - set(parameters_to_delete)
    )
    _validate_expressions(expressions, resolved_parameter_names)
    calculated_names = set(expressions)
    available_transform_targets = resolved_parameter_names | calculated_names
    unknown_transform_targets = {
        item.target_parameter
        for item in request.parameter_transforms or []
        if item.target_parameter not in available_transform_targets
    }
    if unknown_transform_targets:
        raise ValueError(
            "Parameter transforms reference undefined targets: "
            + ", ".join(sorted(unknown_transform_targets))
        )
    source_transforms = [
        item
        for item in request.parameter_transforms or []
        if item.target_parameter not in calculated_names
    ]
    calculated_transforms = [
        item
        for item in request.parameter_transforms or []
        if item.target_parameter in calculated_names
    ]

    imports = ["import numpy as np", "", "from epydemix import EpiModel"]
    if isinstance(request.population, CustomPopulationConfig):
        imports.append("from epydemix.population import Population")
    else:
        imports.append("from epydemix.population import load_epydemix_population")
    if request.parameter_transforms or request.vaccination:
        imports.append("from epydemix.utils.utils import compute_simulation_dates")
    if request.simulation.dt < 1:
        imports.insert(0, "from datetime import date, timedelta")

    sections: list[str] = [
        "# Generated by the epydemix web API. This file calls epydemix directly.",
        *imports,
    ]
    if needs_eigenvalue:
        sections.extend(["", "", _PARAMETER_HELPERS])
    if expressions:
        sections.extend(["", "", _CALCULATION_HELPERS])
    if request.parameter_transforms:
        sections.extend(["", "", _TRANSFORM_HELPERS])
    if request.vaccination:
        sections.extend(["", "", _VACCINATION_HELPER])

    sim = request.simulation
    sections.extend(["", "", f"start_date = {sim.start_date!r}"])
    sections.append(f"end_date = {sim.end_date!r}")
    sections.append(f"dt = {sim.dt!r}")
    if sim.dt < 1:
        sections.append(
            "internal_end_date = (date.fromisoformat(end_date) + timedelta(days=1)).isoformat()"
        )
    else:
        sections.append("internal_end_date = end_date")

    if isinstance(request.population, CustomPopulationConfig):
        population = request.population
        sections.extend(
            [
                "",
                f"population = Population(name={population.name!r})",
                "population.add_population(",
                f"    Nk={_literal([float(value) for value in population.age_groups.values()])},",
                f"    Nk_names={_literal(list(population.age_groups))},",
                ")",
            ]
        )
        for layer, matrix in population.contact_matrices.items():
            sections.extend(
                [
                    "population.add_contact_matrix(",
                    f"    contact_matrix=np.array({_literal(matrix)}, dtype=float),",
                    f"    layer_name={layer!r},",
                    ")",
                ]
            )
    else:
        population = request.population
        sections.extend(
            [
                "",
                "population = load_epydemix_population(",
                f"    population_name={population.name!r},",
                f"    contacts_source={population.contacts_source!r},",
                f"    layers={_literal(population.layers or DEFAULT_LAYERS)},",
                f"    age_group_mapping={_literal(population.age_group_mapping)},",
                '    data_version="v1.2.0",',
                ")",
            ]
        )

    if preset is not None:
        compartments = list(preset.compartments)
        transitions = list(preset.transitions)
    else:
        compartments = list(request.model.compartments or [])
        transitions = [item.model_dump() for item in request.model.transitions or []]

    sections.extend(
        [
            "",
            f"model = EpiModel(compartments={_literal(compartments)})",
            "model.set_population(population)",
        ]
    )
    for name, value in scalar_parameters.items():
        sections.append(f"model.add_parameter(parameter_name={name!r}, value={value!r})")
    for name, value in list_parameters.items():
        sections.append(
            f"model.add_parameter(parameter_name={name!r}, "
            f"value=np.array({_literal(value)}, dtype=float).reshape(1, population.num_groups))"
        )
    for name in parameters_to_delete:
        sections.append(f"model.delete_parameter({name!r})")
    for transition in transitions:
        sections.extend(
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

    for intervention in request.interventions or []:
        sections.extend(
            [
                "",
                "model.add_intervention(",
                f"    layer_name={intervention.layer_name!r},",
                f"    start_date={intervention.start_date!r},",
                f"    end_date={intervention.end_date!r},",
                f"    reduction_factor={intervention.reduction_factor!r},",
                f"    name={(intervention.name or '')!r},",
                ")",
            ]
        )

    sections.extend(_render_transform_calls(request, source_transforms))
    for name in _expression_order(expressions):
        sections.extend(
            [
                "",
                f"# Calculate {name}.",
                "model.add_parameter(",
                f"    parameter_name={name!r},",
                "    value=normalize_calculated_parameter(",
                f"        {_render_expression(expressions[name])},",
                "    ),",
                ")",
            ]
        )
    sections.extend(_render_transform_calls(request, calculated_transforms))

    initial = request.initial_conditions
    if initial is not None and initial.method == "absolute":
        values = initial.compartments or {}
        entries = ",\n".join(
            f"    {name!r}: np.array({_literal(value)}, dtype=float)"
            for name, value in values.items()
        )
        sections.extend(["", f"initial_conditions = {{\n{entries}\n}}"])
    elif initial is not None and initial.method == "percentage":
        percentages = initial.initial_percentages or {}
        sections.extend(
            [
                "",
                "population_by_group = np.asarray(population.Nk, dtype=float)",
                "remaining_population = population_by_group.copy()",
                "initial_conditions = {}",
            ]
        )
        for name, percentage in percentages.items():
            sections.append(
                f"initial_conditions[{name!r}] = population_by_group * ({percentage!r} / 100.0)"
            )
            sections.append(f"remaining_population -= initial_conditions[{name!r}]")
        first = compartments[0]
        sections.extend(
            [
                f"initial_conditions.setdefault({first!r}, np.zeros_like(population_by_group))",
                f"initial_conditions[{first!r}] += remaining_population",
            ]
        )
    elif request.model.preset in {"V-SEIR", "V-SEIHR"}:
        sections.extend(
            [
                "",
                "population_by_group = np.asarray(population.Nk, dtype=float)",
                "seed_count = population_by_group * 0.00025",
                "initial_conditions = {",
                *[
                    f"    {name!r}: np.zeros_like(population_by_group)," for name in compartments
                ],
                "}",
                'initial_conditions["Susceptible"] = population_by_group - 2 * seed_count',
                'initial_conditions["Exposed"] = seed_count',
                'initial_conditions["Infected"] = seed_count',
            ]
        )
    else:
        sections.extend(["", "initial_conditions = None"])

    if request.vaccination is not None:
        flows = request.vaccination.flows
        if flows is None and request.model.preset in {"V-SEIR", "V-SEIHR"}:
            flow_data = [{"source": "Susceptible", "target": "Susceptible_vax"}]
        else:
            flow_data = [item.model_dump() for item in flows or []]
        campaigns = [item.model_dump(mode="json") for item in request.vaccination.campaigns]
        sections.extend(
            [
                "",
                "simulation_dates = compute_simulation_dates(start_date, internal_end_date, dt=dt)",
                "apply_vaccination_campaigns(",
                "    model=model,",
                "    population=population,",
                "    simulation_dates=simulation_dates,",
                "    initial_conditions=initial_conditions,",
                f"    flows={_literal(flow_data)},",
                f"    campaigns={_literal(campaigns)},",
                ")",
            ]
        )

    rng_value = "None" if sim.seed is None else f"np.random.default_rng({sim.seed!r})"
    sections.extend(
        [
            "",
            f"rng = {rng_value}",
            "results = model.run_simulations(",
            "    start_date=start_date,",
            "    end_date=internal_end_date,",
            f"    Nsim={sim.Nsim!r},",
            "    dt=dt,",
            "    initial_conditions_dict=initial_conditions,",
            f"    resample_frequency={sim.resample_frequency!r},",
            "    rng=rng,",
            ")",
        ]
    )
    if sim.dt < 1:
        sections.extend(
            [
                "",
                "cutoff = np.datetime64(end_date)",
                "for trajectory in results.trajectories:",
                "    keep = sum(np.datetime64(value) <= cutoff for value in trajectory.dates)",
                "    trajectory.dates = trajectory.dates[:keep]",
                "    trajectory.compartments = {",
                "        name: values[:keep] for name, values in trajectory.compartments.items()",
                "    }",
                "    trajectory.transitions = {",
                "        name: values[:keep] for name, values in trajectory.transitions.items()",
                "    }",
            ]
        )

    quantiles = request.output.quantiles if request.output and request.output.quantiles else None
    sections.extend(
        [
            "",
            f"quantiles = {_literal(quantiles)}",
            "compartment_quantiles = results.get_quantiles_compartments(quantiles=quantiles)",
            "transition_quantiles = results.get_quantiles_transitions(quantiles=quantiles)",
            'compartment_quantiles.to_csv("compartments.csv", index=False)',
            'transition_quantiles.to_csv("transitions.csv", index=False)',
            'print("Wrote compartments.csv and transitions.csv")',
        ]
    )
    return "\n".join(sections).rstrip() + "\n"
