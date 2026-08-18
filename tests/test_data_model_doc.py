"""docs/data-model.md must list exactly the tables the models define.

The schema doc drifted 22 tables behind the models before this test
existed. Adding a model without a doc row now fails CI instead of
quietly rotting.
"""

import re
from pathlib import Path

from app.database import Base
import app.models  # noqa: F401  (registers every model on Base.metadata)

DOC = Path(__file__).resolve().parents[1] / "docs" / "data-model.md"


def _documented_tables() -> set[str]:
    """Table names from the leading `| \\`name\\` |` cell of each doc row."""
    return set(re.findall(r"^\|\s*`(\w+)`\s*\|", DOC.read_text(), re.MULTILINE))


def test_every_model_table_is_documented():
    missing = set(Base.metadata.tables) - _documented_tables()
    assert not missing, (
        "Tables defined in app/models but missing from docs/data-model.md: "
        + ", ".join(sorted(missing))
    )


def test_no_documented_table_is_phantom():
    phantom = _documented_tables() - set(Base.metadata.tables)
    assert (
        not phantom
    ), "docs/data-model.md lists tables no model defines: " + ", ".join(sorted(phantom))


def test_stated_table_count_matches_reality():
    text = DOC.read_text()
    stated = re.search(r"(\d+) tables", text)
    assert stated, "docs/data-model.md no longer states a table count"
    assert int(stated.group(1)) == len(Base.metadata.tables), (
        f"docs/data-model.md says {stated.group(1)} tables; "
        f"models define {len(Base.metadata.tables)}"
    )
