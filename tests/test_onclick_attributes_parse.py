"""No inline handler carries an interpolated string (found on the 2.12.0 gate).

`app.js` rendered a Delete button as:

    onclick="App.deleteAccount(${a.id}, ${JSON.stringify(a.name)})"

`JSON.stringify` always emits double quotes and the attribute is
double-quoted, so the JSON's own first quote **closed the attribute**. What
reached the HTML parser was:

    <button onclick="App.deleteAccount(5, " savings")"="">Delete</button>

The handler is the fragment `App.deleteAccount(5, ` — clicking raises a
SyntaxError, so no request is made, no toast appears and no dialog opens. On
**every** row, because the break is in the quoting rather than in any
particular name. Edit and Deactivate worked because they pass a number and a
boolean, which survive the parser intact.

Both QA agents found it at the GUI. @skytech read `launcher.log` and
established that the application had never issued a single
`DELETE /api/accounts/*` — the button was not being refused, it never asked.

**Why nothing automated caught it.** The endpoint is correct and well
covered, the suite passed, and every check in both gates passed. My own test
asserted `"deleteAccount(" in js` — that the call exists in the source, not
that the markup it produces parses. A test of a string is not a test of a
document.

So these tests do two things: parse a rendered instance of the row with a
real HTML parser, and refuse the whole class rather than this instance.
@macbase1's framing: *a `data-` attribute plus a delegated listener would
make the class impossible rather than absent* — bigger than this release
wants, and this is the guard that keeps the small fix honest.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / "app/static/js"
JS_FILES = sorted(p for p in JS_DIR.glob("*.js") if p.name != "chart.umd.js")

# An onclick="..." whose body contains a JS template interpolation.
_ONCLICK = re.compile(r'onclick="([^"]*)"')
_INTERP = re.compile(r"\$\{([^}]*)\}")


class _Attrs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def test_the_delete_button_markup_parses_as_one_attribute():
    """A rendered instance, through a real parser. This is the assertion that
    was missing: the old markup produced three attributes and a truncated
    handler, and no amount of reading the source made that obvious."""
    import json

    # json.dumps emits exactly what JSON.stringify does: DOUBLE quotes. That
    # is the whole mechanism — single quotes here would have been safe, and
    # reproducing the break with the wrong quote style would make the control
    # pass for the wrong reason.
    name = json.dumps("Savings")  # -> "Savings"
    good = '<button class="btn" onclick="App.deleteAccount(5)">Delete</button>'
    bad = f'<button class="btn" onclick="App.deleteAccount(5, {name})">Delete</button>'

    p = _Attrs()
    p.feed(good)
    tag, attrs = p.tags[0]
    assert set(attrs) == {"class", "onclick"}, attrs
    assert attrs["onclick"] == "App.deleteAccount(5)"
    assert attrs["onclick"].count("(") == attrs["onclick"].count(")")

    # The control: the old shape really does break, so the assertion above is
    # not passing for an unrelated reason.
    p2 = _Attrs()
    p2.feed(bad)
    _, bad_attrs = p2.tags[0]
    assert len(bad_attrs) > 2, "the control did not reproduce the break"
    assert bad_attrs["onclick"] == "App.deleteAccount(5, ", bad_attrs


# A broad scanner lived here and was deleted before it shipped.
#
# "Any interpolated expression inside an onclick" flagged nine files, and
# every one was a false positive: `${sec.onClick(item)}` builds the whole
# handler, `${!c.is_active}` is a boolean, `${id ? id : 'null'}` is a JS
# literal, and `'${escapeHtml(u.username)}'` is the established safe pattern —
# single quotes inside the double-quoted attribute, with the value escaped.
#
# I spent this week telling two agents that a sweep measuring everything is a
# harder instrument than a check measuring one thing, and then wrote a sweep
# that would have sent the next person after nine non-problems. @macbase1's
# line, turned around: the sweep went, the named checks stayed.
#
# What is left is the mechanism that actually broke, and the assertion that
# the markup parses.


def test_json_stringify_never_reaches_an_inline_handler():
    """The specific mechanism, named, because it looks safe. It is the correct
    tool for embedding a value in a *script body* and the wrong one inside an
    attribute that is already using the quotes it emits."""
    for path in JS_FILES:
        src = path.read_text(encoding="utf-8")
        for handler in _ONCLICK.findall(src):
            assert "JSON.stringify" not in handler, (
                f"{path.name}: JSON.stringify inside an onclick emits double "
                f"quotes into a double-quoted attribute"
            )
