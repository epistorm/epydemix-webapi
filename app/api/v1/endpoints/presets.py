"""Model presets API endpoints.

Lists available predefined epidemic models. Data comes from the single-source
registry in ``app.presets.registry`` so adding a preset doesn't require edits
here.
"""

from fastapi import APIRouter, HTTPException

from ....presets import PRESETS
from ....services.python_export import render_preset_python
from ...responses import PythonSourceResponse, python_source_response
from ..schemas.population import PresetInfo, PresetsListResponse

router = APIRouter()


def _preset_info(definition) -> PresetInfo:
    return PresetInfo(
        name=definition.name,
        description=definition.description,
        compartments=list(definition.compartments),
        parameters=dict(definition.default_parameters),
        transitions=list(definition.transitions),
    )


@router.get(
    "",
    response_model=PresetsListResponse,
    summary="List model presets",
    description="Get information about available predefined epidemic models.",
    operation_id="list_model_presets",
)
async def get_presets() -> PresetsListResponse:
    """List all available model presets.

    Returns information about predefined epidemic models including their
    compartments, default parameters, and transition definitions.
    """
    return PresetsListResponse(
        presets=[_preset_info(d) for d in PRESETS.values()],
    )


@router.get(
    "/{name}/export/python",
    response_class=PythonSourceResponse,
    summary="Export a model preset as Python",
    operation_id="export_model_preset_python",
)
async def export_preset_python(name: str) -> PythonSourceResponse:
    """Export an API preset as explicit epydemix model commands."""
    if name not in PRESETS:
        raise HTTPException(status_code=404, detail=f"Unknown model preset: {name}")
    return python_source_response(render_preset_python(name), f"{name.lower()}_model.py")
