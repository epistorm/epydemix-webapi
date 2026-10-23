"""Custom HTTP responses shared by API endpoints."""

from fastapi.responses import PlainTextResponse


class PythonSourceResponse(PlainTextResponse):
    """A Python source response served as a file attachment."""

    media_type = "text/x-python"


def python_source_response(source: str, filename: str) -> PythonSourceResponse:
    """Return Python source with a safe attachment filename."""
    safe_filename = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in filename
    )
    return PythonSourceResponse(
        source,
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )
