"""Every copy button goes through one helper, and that helper names the
cause it can name (issues #137, #138).

`navigator.clipboard` requires a secure context. The desktop app is served
over plain HTTP and copying works anyway, for exactly one reason: loopback
is a secure origin by specification. `http://127.0.0.1` qualifies;
`http://192.168.x.x` does not.

So every copy button in the product works on the machine running it and
silently stops working for anyone reaching it over a LAN. Nobody who can
reproduce that is looking at it: a developer runs on loopback, and so does
every QA gate on all three platforms. It was found on the 2.11.1 gate by
measuring `isSecureContext`, not by anything failing.

These are source guards rather than behavioural tests for the same reason
`test_css_hidden_and_contrast.py` is: there is no JS harness in this repo,
and the defect lives in code no Python test can execute. A guard that
catches the regression is worth more than no guard at all.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "app/static/js"
UTILS = (JS / "utils.js").read_text(encoding="utf-8")

# Every file that offers the operator a copy button.
CALL_SITES = ("settings.js", "employees.js", "invoices.js", "reseller_permits.js")


def test_the_helper_exists_and_is_in_utils():
    """utils.js loads before every page script in index.html, so the helper
    has to live there for the call sites to see it."""
    assert "async function copyToClipboard(" in UTILS
    index = (ROOT / "index.html").read_text(encoding="utf-8")
    utils_at = index.index("/static/js/utils.js")
    for name in CALL_SITES:
        assert (
            index.index(f"/static/js/{name}") > utils_at
        ), f"{name} is loaded before utils.js; copyToClipboard would be undefined"


@pytest.mark.parametrize("name", CALL_SITES)
def test_no_page_calls_the_clipboard_api_directly(name):
    """The whole point of the helper is that the four call sites cannot
    drift apart again. Before this, `invoices.js` had no guard at all and
    reported a clipboard refusal as an API error, `reseller_permits.js`
    fell back to a `window.prompt`, and the other two carried two slightly
    different copies of the same check."""
    src = (JS / name).read_text(encoding="utf-8")
    assert (
        "navigator.clipboard" not in src
    ), f"{name} calls navigator.clipboard directly instead of copyToClipboard()"


def test_the_helper_names_the_insecure_context_case():
    """`isSecureContext` is the whole diagnosis. Without it the message is
    'clipboard unavailable', which tells a LAN user nothing they can act
    on — and they are the only people who ever see it."""
    assert "window.isSecureContext" in UTILS
    branch = UTILS[UTILS.index("window.isSecureContext") :]
    branch = branch[: branch.index("}")]
    assert "secure connection" in branch.lower()


def test_the_fallback_selects_the_text():
    """The point of selecting it is that the recovery becomes one keystroke
    instead of an instruction to aim a mouse at a monospace blob — which is
    how somebody ended up screenshotting an API token to keep it."""
    assert "_selectElementText" in UTILS
    assert "selectNodeContents" in UTILS
    assert "Ctrl+C" in UTILS


def test_the_api_token_reveal_passes_its_element_to_the_helper():
    """The token is the case that matters most: shown exactly once, and the
    element is on screen when the copy fails, so it can be selected."""
    src = (JS / "settings.js").read_text(encoding="utf-8")
    m = re.search(r"copyApiTokenSecret\(\)\s*\{(.+?)\n    \},", src, re.S)
    assert m, "copyApiTokenSecret() not found"
    assert "copyToClipboard(" in m.group(1)
    assert "el)" in m.group(
        1
    ), "the reveal element is not passed, so the fallback cannot select the token"


def test_the_created_toast_tells_you_to_press_copy():
    """Issue #138. 'copy it now' reads as a report of something already
    done — a tester read it that way, went to paste, and got nothing. On a
    secret shown exactly once, believing it is already on the clipboard
    costs you your only look."""
    src = (JS / "settings.js").read_text(encoding="utf-8")
    assert "Token created — press Copy below" in src
    assert "Token created — copy it now" not in src
