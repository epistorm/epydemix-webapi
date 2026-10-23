"""Helper source embedded into generated epydemix scripts."""

_PARAMETER_HELPERS = '''
def calculate_dominant_contact_eigenvalue(population) -> float:
    """Calculate the dominant eigenvalue of all contact layers combined."""
    matrices = population.contact_matrices
    if not matrices:
        raise ValueError("The population has no contact matrices.")
    combined_matrix = sum(
        np.asarray(matrix, dtype=float)
        for matrix in matrices.values()
    )
    eigenvalues = np.linalg.eigvals(combined_matrix)
    return float(np.max(np.abs(eigenvalues)))


def calculate_transmission_rate_from_r0(r0, recovery_rate, contact_eigenvalue):
    """Convert R0 into a transmission rate for an SIR-like model."""
    return r0 * recovery_rate / contact_eigenvalue
'''.strip()


_CALCULATION_HELPERS = '''
def get_parameter_for_calculation(model, name):
    """Return a parameter with time-only arrays prepared for age broadcasting."""
    value = model.get_parameter(name)
    if isinstance(value, np.ndarray) and value.ndim == 1:
        return value.reshape(-1, 1)
    return value


def normalize_calculated_parameter(value):
    """Convert calculation-only helper shapes back to native parameter shapes."""
    if not isinstance(value, np.ndarray):
        return value
    if value.ndim == 2 and value.shape[1] == 1 and value.shape[0] != 1:
        return np.ascontiguousarray(value[:, 0])
    if value.ndim == 2 and value.shape == (1, 1):
        return float(value[0, 0])
    if value.ndim == 0:
        return float(value)
    return value.copy()
'''.strip()


_TRANSFORM_HELPERS = '''
def _broadcast_parameter(value, number_of_dates, number_of_groups):
    """Broadcast a scalar, time series, or age vector to a time-by-age array."""
    existing = np.asarray(value, dtype=float)
    if existing.ndim == 0:
        return np.full((number_of_dates, number_of_groups), float(existing))
    if existing.ndim == 1 and len(existing) == number_of_dates:
        return np.broadcast_to(existing[:, None], (number_of_dates, number_of_groups)).copy()
    if existing.ndim == 1 and len(existing) == number_of_groups:
        return np.broadcast_to(existing[None, :], (number_of_dates, number_of_groups)).copy()
    if existing.shape == (1, number_of_groups):
        return np.broadcast_to(existing, (number_of_dates, number_of_groups)).copy()
    if existing.shape == (number_of_dates, number_of_groups):
        return existing.copy()
    raise ValueError(f"Cannot broadcast parameter shape {existing.shape}.")


def _multiply_parameter(value, factors):
    """Multiply a scalar or age-varying parameter by time-varying factors."""
    existing = np.asarray(value, dtype=float)
    factors = np.asarray(factors, dtype=float)
    if existing.ndim == 0:
        return float(existing) * factors
    if existing.ndim == 1 and len(existing) == len(factors):
        return existing * factors
    if existing.ndim == 1:
        return factors[:, None] * existing[None, :]
    if existing.ndim == 2:
        return factors[:, None] * existing
    raise ValueError(f"Unsupported parameter shape: {existing.shape}")


def apply_balcan_seasonality(
    value,
    start_date,
    end_date,
    max_date,
    min_value,
    min_date=None,
    max_value=1.0,
    dt=1.0,
):
    """Apply Balcan seasonality to a scalar or age-varying parameter."""
    dates = compute_simulation_dates(start_date, end_date, dt=dt)
    start = np.datetime64(start_date)
    maximum = np.datetime64(max_date)
    time_days = ((dates - start) / np.timedelta64(1, "D")).astype(float)
    maximum_day = float((maximum - start) / np.timedelta64(1, "D"))
    if min_date is None:
        period_days = 365.0
    else:
        minimum = np.datetime64(min_date)
        minimum_day = float((minimum - start) / np.timedelta64(1, "D"))
        period_days = 2 * abs(minimum_day - maximum_day)
    minimum_ratio = min_value / max_value
    factors = (
        (1 - minimum_ratio)
        * np.sin((2 * np.pi / period_days) * (time_days - maximum_day) + np.pi / 2)
        + 1
        + minimum_ratio
    ) / 2
    return _multiply_parameter(value, factors)


def apply_parameter_scaling(
    value,
    start_date,
    end_date,
    scaling_start,
    scaling_end,
    factor,
    dt=1.0,
):
    """Multiply a parameter inside an inclusive date window."""
    dates = compute_simulation_dates(start_date, end_date, dt=dt)
    active = (
        (dates >= np.datetime64(scaling_start))
        & (dates <= np.datetime64(scaling_end))
    )
    factors = np.where(active, float(factor), 1.0)
    return _multiply_parameter(value, factors)


def apply_parameter_override(
    value,
    override_value,
    start_date,
    end_date,
    override_start,
    override_end,
    number_of_groups,
    dt=1.0,
):
    """Replace a parameter inside an inclusive date window."""
    dates = compute_simulation_dates(start_date, end_date, dt=dt)
    result = _broadcast_parameter(value, len(dates), number_of_groups)
    active = (
        (dates >= np.datetime64(override_start))
        & (dates <= np.datetime64(override_end))
    )
    result[active, :] = np.asarray(override_value, dtype=float)
    return result
'''.strip()


_VACCINATION_HELPER = '''
def apply_vaccination_campaigns(model, population, simulation_dates, initial_conditions, flows, campaigns):
    """Register and add API-equivalent native vaccination transitions."""
    age_names = [str(name) for name in population.Nk_names]
    compartment_indices = {name: index for index, name in enumerate(model.compartments)}
    denominator_sources = tuple(flow["source"] for flow in flows)
    resolved_campaigns = []

    for campaign in campaigns:
        target_names = campaign["target_age_groups"] or age_names
        target_indices = np.asarray(
            [age_names.index(name) for name in target_names],
            dtype=np.int64,
        )
        active = (
            (simulation_dates >= np.datetime64(campaign["start_date"]))
            & (simulation_dates <= np.datetime64(campaign["end_date"]))
        )
        rollout = campaign["rollout"]
        rate_based = rollout["type"] == "fixed_rate"
        value = rollout["rate"] if rate_based else rollout["daily_doses"]
        schedule = np.where(active, float(value), 0.0)

        threshold = None
        vaccinated_indices = None
        coverage = campaign.get("coverage")
        if coverage is not None:
            if initial_conditions is None:
                raise ValueError("Coverage-capped vaccination requires initial conditions.")
            initial_population = float(
                sum(values[target_indices].sum() for values in initial_conditions.values())
            )
            threshold = coverage["fraction"] * initial_population
            vaccinated_indices = np.asarray(
                [compartment_indices[name] for name in coverage["compartments"]],
                dtype=np.int64,
            )

        resolved_campaigns.append({
            "schedule": schedule,
            "target_indices": target_indices,
            "rate_based": rate_based,
            "coverage_threshold": threshold,
            "vaccinated_indices": vaccinated_indices,
        })

    def calculate_vaccination_rate(params, data):
        """Calculate the per-age vaccination rate for one simulation step."""
        rate = np.zeros(population.num_groups, dtype=np.float64)
        eligible_populations = None
        for campaign in resolved_campaigns:
            value = campaign["schedule"][data["t"]]
            if value <= 0:
                continue
            targets = campaign["target_indices"]
            threshold = campaign["coverage_threshold"]
            vaccinated_indices = campaign["vaccinated_indices"]
            if threshold is not None and vaccinated_indices is not None:
                vaccinated = float(
                    sum(data["pop"][index][targets].sum() for index in vaccinated_indices)
                )
                if vaccinated >= threshold:
                    continue
            if campaign["rate_based"]:
                rate[targets] += value
            else:
                if eligible_populations is None:
                    eligible_populations = [
                        data["pop"][data["comp_indices"][name]]
                        for name in params["denominator_sources"]
                    ]
                eligible = float(sum(values[targets].sum() for values in eligible_populations))
                if eligible > 0:
                    rate[targets] += value / eligible
        return rate

    model.register_transition_kind("vaccination", calculate_vaccination_rate)
    for flow in flows:
        if flow["target"] is not None:
            model.add_transition(
                source=flow["source"],
                target=flow["target"],
                kind="vaccination",
                params={
                    "source": flow["source"],
                    "denominator_sources": denominator_sources,
                },
            )
'''.strip()
