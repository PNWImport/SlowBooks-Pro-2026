"""Exercise the server backup script with a disposable pg_dump executable."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(
    os.name != "posix" or not shutil.which("bash"), reason="Bash required"
)
@pytest.mark.parametrize("fails", [False, True])
def test_backup_cleanup_and_retention(tmp_path, fails):
    if not shutil.which("sort") or "GNU" not in subprocess.check_output(
        ["sort", "--version"], text=True
    ):
        pytest.skip("GNU utilities required by Linux server backup")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    dump = bin_dir / "pg_dump"
    dump.write_text(
        "#!/bin/sh\nprintf 'partial or complete dump'\nexit " + str(int(fails)) + "\n"
    )
    dump.chmod(0o755)
    backup_dir = tmp_path / "backups with spaces"
    backup_dir.mkdir()
    for i in range(31):
        old = backup_dir / f"bookkeeper_old {i:02}.sql.gz"
        old.write_text("old backup")
        os.utime(old, (1000 + i, 1000 + i))
    unrelated = backup_dir / "keep.txt"
    unrelated.write_text("keep")
    result = subprocess.run(
        ["bash", str(Path(__file__).resolve().parents[1] / "scripts/backup.sh")],
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "BACKUP_DIR": str(backup_dir),
        },
        capture_output=True,
        text=True,
    )
    remaining = list(backup_dir.glob("bookkeeper_*.sql.gz"))
    assert result.returncode == int(fails), result.stderr
    assert unrelated.read_text(encoding="utf-8") == "keep"
    if fails:
        assert len(remaining) == 31
        assert all(p.name.startswith("bookkeeper_old ") for p in remaining)
        assert "Backup failed" in result.stdout
    else:
        assert len(remaining) == 30
        assert not (backup_dir / "bookkeeper_old 00.sql.gz").exists()
        assert not (backup_dir / "bookkeeper_old 01.sql.gz").exists()
        assert (backup_dir / "bookkeeper_old 30.sql.gz").exists()
