"""OCR subprocess contracts using synthetic outputs, without native binaries."""

import subprocess
from types import SimpleNamespace

import pytest

from app.services import ocr_service as ocr


@pytest.mark.parametrize("method", ["ocr_image_bytes", "ocr_image_words"])
@pytest.mark.parametrize("failure", ["timeout", "missing", "exit"])
def test_process_errors_are_controlled(monkeypatch, method, failure):
    monkeypatch.setattr(ocr, "tesseract_cmd", lambda: None)

    def run(args, **kwargs):
        assert args[:3] == ["tesseract", "stdin", "stdout"]
        assert kwargs["input"] == b"synthetic-image"
        assert kwargs["timeout"] == ocr.OCR_TIMEOUT_SECONDS
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        if failure == "missing":
            raise FileNotFoundError("synthetic missing binary")
        return SimpleNamespace(returncode=1, stderr=b"synthetic failure " * 100)

    monkeypatch.setattr(ocr.subprocess, "run", run)
    with pytest.raises(ocr.OCRRuntimeError) as exc:
        getattr(ocr, method)(b"synthetic-image")
    assert len(str(exc.value)) < 400


@pytest.mark.parametrize("method", ["ocr_image_bytes", "ocr_image_words"])
def test_language_is_single_argument_and_empty_output_is_valid(monkeypatch, method):
    monkeypatch.setattr(ocr, "tesseract_cmd", lambda: "/synthetic/tesseract")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert "shell" not in kwargs
        return SimpleNamespace(returncode=0, stdout=None)

    monkeypatch.setattr(ocr.subprocess, "run", run)
    result = getattr(ocr, method)(b"synthetic", lang="eng+fra")
    assert calls[0][5:7] == ["-l", "eng+fra"]
    assert result == ("" if method == "ocr_image_bytes" else ("", []))


def test_tsv_malformed_rows_and_paragraph_boundaries():
    header = "level\tpage\tblock\tpar\tline\tword\tleft\ttop\twidth\theight\tconf\ttext"
    rows = [
        "short",
        "bad\t1\t1\t1\t1\t1\t0\t0\t1\t1\t90\tignored",
        "4\t1\t1\t1\t1\t1\t0\t0\t1\t1\t90\tignored",
        "5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t90\t   ",
        "5\t1\t1\t1\t1\t1\t10\t20\t30\t40\t95.5\tSynthetic",
        "5\t1\t1\t1\t1\t2\tbad\t20\t30\t40\t95\tmerchant",
        "5\t1\t2\t1\t1\t1\t10\t60\t30\t40\t90\tTotal",
    ]
    text, words = ocr._parse_tesseract_tsv("\n".join([header, *rows]))
    assert text == "Synthetic merchant\n\nTotal"
    assert words[0] == {
        "text": "Synthetic",
        "left": 10,
        "top": 20,
        "width": 30,
        "height": 40,
        "conf": 95.5,
    }
    assert words[1]["left"] == words[1]["height"] == 0
    assert words[1]["conf"] == -1.0
