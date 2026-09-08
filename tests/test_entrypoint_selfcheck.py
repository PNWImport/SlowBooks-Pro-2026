"""Exercise the real boot script without a database or server process."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("check_status", [0, 1, 2])
def test_boot_requires_successful_wiring_check(tmp_path, check_status):
    for name, body in {
        "python": 'if [ "$1" = "-c" ]; then exit 0; fi\nexit "$CHECK_STATUS"',
        "uvicorn": 'echo "SERVER_STARTED"',
    }.items():
        executable = tmp_path / name
        executable.write_text("#!/bin/bash\n" + body + "\n")
        executable.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:/usr/bin:/bin",
        "WAIT_FOR_POSTGRES": "0",
        "RUN_MIGRATIONS": "0",
        "SKIP_BOOT_SELFCHECK": "",
        "CHECK_STATUS": str(check_status),
    }
    result = subprocess.run(
        ["bash", str(Path(__file__).resolve().parents[1] / "docker-entrypoint.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert (result.returncode == 0) == (check_status == 0)
    assert ("SERVER_STARTED" in result.stdout) == (check_status == 0)
