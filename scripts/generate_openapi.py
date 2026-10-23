"""Generate ``web/static/openapi.json`` from the live FastAPI app.

The docs site serves a static copy of the OpenAPI schema at
``/openapi.json``. This script dumps ``app.openapi()`` to that file, minified
(no indentation) to keep diffs small and version-only on a release.

The schema's ``info.version`` comes from ``settings.app_version``, which reads
the installed package metadata. After a version bump, run ``uv sync`` first so
the installed metadata matches ``pyproject.toml``; otherwise the regenerated
file keeps the stale version.

Re-run after changing routes, schemas, or the version:

    uv run python scripts/generate_openapi.py
"""

from __future__ import annotations

import json
from pathlib import Path

from app.main import app

OUTPUT = Path(__file__).resolve().parents[1] / "web" / "static" / "openapi.json"


def main() -> None:
    schema = app.openapi()
    with OUTPUT.open("w") as f:
        json.dump(schema, f, separators=(",", ":"))
    print(f"Wrote {OUTPUT} (version {schema['info']['version']})")


if __name__ == "__main__":
    main()
