"""Parameter transform schemas: balcan / scale / override (discriminated union)."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from ..common import DateStr


class _BaseTransform(BaseModel):
    """Common fields for all parameter transforms."""

    target_parameter: str = Field(
        ...,
        description="Name of the model parameter to transform. Must already be defined in `model.parameters`.",
    )


class BalcanTransform(_BaseTransform):
    """Balcan-style sinusoidal seasonality applied across the simulation timeline (Balcan D et al. J. Comput. Sci. 2010; https://doi.org/10.1016/j.jocs.2010.07.002).

    The transform is **multiplicative on top of the baseline parameter**. At each
    step, the existing value of `target_parameter` is multiplied by a sinusoidal
    factor that reaches `1.0` on `max_date` (the seasonal peak) and
    `min_value / max_value` on `min_date` (the seasonal trough). The effective
    parameter therefore swings between `baseline` (peak) and
    `baseline * (min_value / max_value)` (trough).

    **Recommended usage**: leave `max_value` at its default of `1.0` and only set
    `min_value` to express the seasonal floor as a fraction of the baseline. For
    example, with `min_value=0.1`, the parameter drops to 10% of its baseline at
    the trough.

    Setting `max_value` to anything other than `1` only matters if you want to
    express both bounds in absolute units (mirroring the notation in Balcan et al.
    2010). Note that the multiplier shape depends only on the **ratio**
    `min_value / max_value`: `(max_value=0.4, min_value=0.1)` produces exactly
    the same dynamics as `(max_value=1, min_value=0.25)` (both have ratio `0.25`).
    """

    method: Literal["balcan"]
    max_date: DateStr = Field(
        ...,
        description="Date when the multiplier reaches its peak (1.0), `YYYY-MM-DD`.",
    )
    min_value: float = Field(
        ...,
        description=(
            "Lower bound of the seasonal scaling. The multiplier reaches "
            "`min_value / max_value` at the trough. With the default "
            "`max_value=1`, this is simply the fraction of baseline at the "
            "trough (e.g. `0.1` means 10% of baseline)."
        ),
    )
    max_value: float = Field(
        default=1.0,
        description=(
            "Upper bound of the seasonal scaling. Defaults to `1.0`, which makes "
            "the peak exactly equal to the baseline parameter. Only set this if "
            "you want to express both bounds in absolute units; the multiplier "
            "shape depends only on the ratio `min_value / max_value`."
        ),
    )
    min_date: DateStr | None = Field(
        default=None,
        description=(
            "Date of trough, `YYYY-MM-DD`. If set, period = `2 * |min_date - max_date|`. "
            "If omitted, period defaults to 365 days."
        ),
    )


class ScaleTransform(_BaseTransform):
    """Multiplicative scaling applied during a date window.

    Outside `[start_date, end_date]` the multiplier is 1.0; inside it is
    `factor`. Composes multiplicatively with other transforms on the same
    parameter in the order listed.
    """

    method: Literal["scale"]
    start_date: DateStr = Field(..., description="Window start, `YYYY-MM-DD`.")
    end_date: DateStr = Field(..., description="Window end, `YYYY-MM-DD`. Must be `>= start_date`.")
    factor: float = Field(
        ..., description="Multiplicative factor applied within `[start_date, end_date]`."
    )

    @model_validator(mode="after")
    def _validate_window(self) -> "ScaleTransform":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        return self


class OverrideTransform(_BaseTransform):
    """Absolute value override during a date window.

    Replaces the parameter wholesale during `[start_date, end_date]`. Applied
    last in the transform pass, so an override always wins for its window
    regardless of where it appears in the list. The override is baked into
    `model.parameters`, so calculated parameters that reference the target
    pick up the overridden value automatically (the same as `balcan` /
    `scale`).
    """

    method: Literal["override"]
    start_date: DateStr = Field(..., description="Window start, `YYYY-MM-DD`.")
    end_date: DateStr = Field(..., description="Window end, `YYYY-MM-DD`. Must be `>= start_date`.")
    value: float | list[float] = Field(
        ...,
        description=(
            "Absolute replacement value during the window. Scalar for uniform, "
            "or a list of one value per age group (length must match the resolved population)."
        ),
    )

    @model_validator(mode="after")
    def _validate_window(self) -> "OverrideTransform":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        return self


ParameterTransformConfig = Annotated[
    BalcanTransform | ScaleTransform | OverrideTransform,
    Field(discriminator="method"),
]
