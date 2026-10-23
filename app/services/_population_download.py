"""Download population CSVs under the parent process's wall-clock deadline."""

import json
import socket
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen


def main() -> int:
    request = json.load(sys.stdin)
    deadline = time.monotonic() + request["timeout"]
    try:
        for relative_path in request["paths"]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Population download deadline exceeded")
            target = Path(request["directory"]) / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            url = request["base_url"] + quote(relative_path, safe="/")
            with urlopen(url, timeout=remaining) as response, target.open("wb") as output:
                while chunk := response.read(64 * 1024):
                    output.write(chunk)
    except Exception as exc:
        timed_out = isinstance(exc, (TimeoutError, socket.timeout)) or (
            isinstance(exc, URLError) and isinstance(exc.reason, TimeoutError)
        )
        json.dump(
            {"type": "TimeoutError" if timed_out else type(exc).__name__, "message": str(exc)},
            sys.stdout,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
