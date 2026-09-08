"""Container-local liveness probe.

The app returns 200 in the localhost Compose profile and redirects HTTP to
HTTPS when a production proxy profile is active. Both prove the internal
worker is answering; following the redirect would incorrectly probe a TLS
listener that belongs to the external proxy, not this container.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def probe(url: str) -> int:
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(url, timeout=3) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()
    except (OSError, urllib.error.URLError):
        return 1
    return 0 if status in {200, 307, 308} else 1


if __name__ == "__main__":
    raise SystemExit(
        probe(os.getenv("SLOWBOOKS_HEALTH_URL", "http://127.0.0.1:3001/health"))
    )
