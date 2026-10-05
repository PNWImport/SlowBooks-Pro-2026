"""Upstream desktop error wording must not include library-supplied text."""

import pytest
from PIL import Image

from app.services import ai_service, ocr_regions


def test_worker_url_parser_error_is_sanitized(monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("private-parser-detail")

    monkeypatch.setattr(ai_service, "urlparse", fail)
    with pytest.raises(ValueError) as exc:
        ai_service.validate_worker_url("https://example.test")
    assert str(exc.value) == "worker_url is not a parseable URL"


def test_stored_scan_decode_error_is_sanitized(monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("private-image-detail")

    monkeypatch.setattr(Image, "open", fail)
    with pytest.raises(ocr_regions.RegionError) as exc:
        ocr_regions._load_image(b"image")
    assert str(exc.value) == "Could not read the stored scan image"
