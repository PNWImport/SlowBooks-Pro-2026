"""Native PDF availability must not decide whether ordinary app code imports."""

import os
from pathlib import Path
import subprocess
import sys


def test_pdf_service_import_does_not_load_weasyprint():
    probe = """
import importlib.abc
import sys
class RefuseWeasyPrint(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'weasyprint' or fullname.startswith('weasyprint.'):
            raise OSError('synthetic missing pango stack')
sys.meta_path.insert(0, RefuseWeasyPrint())
from app.services import pdf_service
assert 'weasyprint' not in sys.modules
assert pdf_service._FETCHER is None
try:
    pdf_service.render_pdf('<p>test</p>')
except OSError as exc:
    assert str(exc) == 'synthetic missing pango stack'
else:
    raise AssertionError('rendering should still require the native stack')
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "DATABASE_URL": "sqlite:///:memory:"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
