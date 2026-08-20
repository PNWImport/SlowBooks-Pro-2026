"""Every backend-only route still sits behind the session gate.

`_INTENTIONAL_BACKEND_ONLY` in test_wiring.py marks routes with no SPA
caller. That is a UI-coverage marker and says nothing about access
control — a route with no button is not a route with no lock. This
module walks that same list and proves each entry either requires a
session or is on the deliberate auth-exempt list in app/main.py, so the
two concepts can never be confused into an actual hole.

Adding an entry to the backend-only allowlist without auth now fails
here.
"""

import re
from pathlib import Path

import pytest

WIRING = Path(__file__).resolve().parent / "test_wiring.py"
MAIN = Path(__file__).resolve().parents[1] / "app" / "main.py"


def _backend_only() -> list[tuple[str, str]]:
    """(method, path) pairs from test_wiring's _INTENTIONAL_BACKEND_ONLY."""
    text = WIRING.read_text()
    start = text.index("_INTENTIONAL_BACKEND_ONLY")
    block = text[start : text.index("\n}\n", start)]
    return re.findall(r'\("(\w+)",\s*"([^"]+)"\)', block)


def _auth_exempt() -> tuple[tuple[str, ...], set[str]]:
    """The exemption lists as app/main.py actually declares them."""
    text = MAIN.read_text()
    prefixes = tuple(
        re.findall(
            r'"([^"]+)"',
            text[
                text.index("_AUTH_EXEMPT_PREFIXES = (") : text.index(
                    "_AUTH_EXEMPT_EXACT"
                )
            ],
        )
    )
    exact_block = text[text.index("_AUTH_EXEMPT_EXACT = {") :]
    exact = set(re.findall(r'"([^"]+)"', exact_block[: exact_block.index("}")]))
    return prefixes, exact


def _concrete(path: str) -> str:
    """Substitute path params so the URL routes to a real handler."""
    return re.sub(r"\{[^}]+\}", "1", path)


def test_backend_only_list_is_not_empty():
    assert len(_backend_only()) > 10, "collector broke — allowlist looks empty"


@pytest.mark.parametrize("method,path", _backend_only())
def test_backend_only_route_requires_session(method, path, unauthed_client):
    prefixes, exact = _auth_exempt()
    if path in exact or path.startswith(prefixes):
        pytest.skip(f"{path} is deliberately auth-exempt in app/main.py")

    resp = unauthed_client.request(method, _concrete(path))
    assert resp.status_code == 401, (
        f"{method} {path} returned {resp.status_code} without a session — "
        "a backend-only route must still require auth"
    )
