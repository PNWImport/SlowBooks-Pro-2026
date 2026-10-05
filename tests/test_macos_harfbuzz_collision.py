"""The macOS bundle must contain exactly one HarfBuzz (issue #141).

Reported by mdornich after a locally built `.app` crashed in native code on
its first PDF render. PyInstaller collects two HarfBuzz builds:

    Contents/Frameworks/PIL/.dylibs/libharfbuzz.0.dylib   Pillow's,   ~1.81 MB
    Contents/Frameworks/libharfbuzz.dylib                 Homebrew's, ~1.32 MB
    Contents/Frameworks/libharfbuzz-subset.0.dylib        Homebrew's, ~1.36 MB

Both answer to `@rpath/libharfbuzz.0.dylib`, so whichever loads first wins
for the whole process. The spec seeds Homebrew's under the versioned name,
but PyInstaller's PIL hook wins the filename collision and replaces it with a
symlink into `PIL/`. Pango then gets Pillow's HarfBuzz while
`libharfbuzz-subset` is Homebrew's — and that symbol set exists only in the
Homebrew build.

An earlier version of this fix claimed the pinned Pillow wheel ships no raqm
or fribidi, so shaping is off and its HarfBuzz is inert. @macbase1 measured
pillow 12.3.0 from that same pin reporting `harfbuzz: True, raqm: True`. The
conclusion is unchanged — nothing in `app/` draws text with Pillow — but it
rests on that argument alone, which is what
`test_nothing_in_the_app_draws_text_with_pillow` guards.

These are source guards. The real check is a built bundle on an Apple
Silicon Mac, which is the QA agent's job and is asked for in testing-repo
issue #47. What is guarded here is that the spec keeps the properties the
fix depends on, because those are what a later edit would quietly remove.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = (ROOT / "packaging/macos/SlowBooksPro-mac.spec").read_text(encoding="utf-8")


def test_the_spec_excludes_the_module_rather_than_dropping_the_library():
    """@macbase1 measured both, on a box where they forced the collision.

    Dropping Pillow's dylib from `a.binaries` after Analysis fails two ways:
    alone it leaves ZERO versioned copies, because Homebrew's is already
    sitting under the unversioned name — an affected builder cannot build at
    all. And re-seeding the versioned name afterwards BUILDS and produces a
    DANGLING SYMLINK into `PIL/`, because PyInstaller creates the cross-link
    before the spec removes the file under it. That bundle signs, notarizes
    and dies at the first PDF: the original symptom, reached by the repair.

    Excluding the module is early enough — the library is never collected.
    """
    assert '"PIL._imagingft"' in SPEC
    assert '"PIL.ImageFont"' in SPEC
    assert "a.binaries.remove" not in SPEC, (
        "dropping the library after collection is the approach that produces "
        "a dangling symlink or a zero-copy build"
    )


def test_the_spec_still_seeds_homebrews_versioned_harfbuzz():
    """The half that makes dropping Pillow's copy safe rather than fatal.

    Homebrew's library must end up AT `libharfbuzz.0.dylib`. If it only lands
    under the unversioned name, `_imagingft`'s `@rpath/libharfbuzz.0.dylib`
    goes from resolving the wrong library to resolving nothing — an import
    failure instead of a render crash, which is worse and easier to ship."""
    assert '_brew_library("harfbuzz", "libharfbuzz.0.dylib")' in SPEC
    assert '_brew_library("harfbuzz", "libharfbuzz-subset.0.dylib")' in SPEC


def test_the_build_fails_loudly_rather_than_shipping_a_collision():
    """A bundle nobody looks inside is exactly how this shipped in the first
    place. Zero copies and two copies are both build failures now."""
    assert "expected exactly one libharfbuzz.0.dylib" in SPEC
    assert SPEC.count("raise SystemExit") >= 2
    # The assertion is the half that survives a future hook or collect_all
    # reintroducing the collision, so it stays even though the excludes
    # should mean it never fires.


def test_nothing_in_the_app_draws_text_with_pillow():
    """Why dropping Pillow's HarfBuzz is safe, asserted rather than assumed.

    If someone later imports ImageDraw or ImageFont, complex-text shaping
    becomes reachable and this decision needs revisiting — so the assumption
    should fail out loud at that moment, not in a crash report."""
    offenders = []
    for path in (ROOT / "app").rglob("*.py"):
        src = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"\b(ImageDraw|ImageFont)\b", src):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, (
        "app/ now draws text with Pillow: " + ", ".join(offenders) + ". "
        "Pillow's HarfBuzz is dropped from the macOS bundle (#141) on the "
        "grounds that nothing asks Pillow to shape text. Re-check that."
    )
