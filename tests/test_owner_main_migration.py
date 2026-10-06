"""Upgrade either published parent without losing existing settings."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("parent", ["base", "ff00aabb1122", "d6e7f8a9b0c1"])
def test_owner_merge_upgrade_from_each_parent(tmp_path, parent):
    # A literal percent also exercises Alembic's ConfigParser escaping.
    path = tmp_path / "company%name.db"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{path}",
        "APP_DEBUG": "true",
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    def upgrade(revision):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", revision],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    marker = "synthetic-preservation-check-" * 60
    if parent != "base":
        upgrade(parent)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                ("merge_preservation_probe", marker),
            )
    upgrade("head")
    upgrade("head")
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchall() == [
            ("b7fringe2026105",)
        ]
        # Whichever parent ran first, no money column is left at precision 12.
        narrow = [
            (table, row[1])
            for (table,) in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            for row in db.execute(f'PRAGMA table_info("{table}")')
            if row[2].upper().replace(" ", "") == "NUMERIC(12,2)"
        ]
        assert narrow == []
        pay_schedule_columns = {
            row[1] for row in db.execute("PRAGMA table_info(pay_schedules)")
        }
        assert "blackout_dates" in pay_schedule_columns
        columns = {row[1]: row[2] for row in db.execute("PRAGMA table_info(settings)")}
        assert columns["value"].upper() == "TEXT"
        if parent != "base":
            assert db.execute(
                "SELECT value FROM settings WHERE key = ?",
                ("merge_preservation_probe",),
            ).fetchone() == (marker,)
