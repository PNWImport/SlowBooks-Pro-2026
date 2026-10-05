"""Image preprocessing and converter contracts; synthetic data, no native tools."""

import io
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from app.services import ocr_service as ocr
from app.services import pdf_raster


@pytest.fixture(autouse=True)
def isolate_poppler_contracts(monkeypatch):
    monkeypatch.setattr(pdf_raster, "windows_available", lambda: False)
    monkeypatch.setattr(pdf_raster, "macos_available", lambda: False)


@pytest.mark.parametrize("height,factor", [(600, 3), (1800, 1), (2000, 1)])
def test_preprocessing_size_and_binary_pixels(height, factor):
    source = Image.new("RGB", (20, height), "white")
    source.paste("black", (0, 0, 10, height))
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")
    output, scale = ocr.preprocess_page(buffer.getvalue())
    with Image.open(io.BytesIO(output)) as result:
        assert result.format == "PNG" and result.mode == "L"
        assert result.size == (20 * factor, height * factor)
        assert {color for count, color in result.getcolors()} == {0, 255}
    assert scale == factor


def test_undecodable_image_falls_back_without_losing_bytes():
    assert ocr.preprocess_page(b"synthetic invalid image") == (
        b"synthetic invalid image",
        1,
    )


@pytest.mark.parametrize(
    "info_mode", ["pages", "no-count", "error", "timeout", "missing"]
)
def test_rasterizer_first_page_and_temporary_cleanup(monkeypatch, info_mode):
    monkeypatch.setattr(ocr, "poppler_available", lambda: True)
    paths = []

    def run(args, **kwargs):
        assert "shell" not in kwargs
        if args[0] == "pdfinfo":
            path = Path(args[1])
            paths.append(path.parent)
            assert path.read_bytes() == b"synthetic input"
            if info_mode == "timeout":
                raise subprocess.TimeoutExpired(args, 15)
            if info_mode == "missing":
                raise FileNotFoundError("synthetic missing pdfinfo")
            return SimpleNamespace(
                returncode=1 if info_mode == "error" else 0,
                stdout="Pages: 3\n" if info_mode == "pages" else "Title: Synthetic\n",
            )
        assert args[:9] == [
            "pdftoppm",
            "-png",
            "-r",
            "144",
            "-f",
            "1",
            "-l",
            "1",
            "-singlefile",
        ]
        assert kwargs["timeout"] == 30
        Path(args[-1] + ".png").write_bytes(b"synthetic converter output")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ocr.subprocess, "run", run)
    assert ocr.rasterize_pdf(b"synthetic input", dpi=144) == (
        b"synthetic converter output",
        3 if info_mode == "pages" else 1,
    )
    assert paths and all(not path.exists() for path in paths)


@pytest.mark.parametrize(
    "mode", ["timeout", "missing", "exit", "empty-stderr", "no-output"]
)
def test_failed_conversion_cleans_temp_files(monkeypatch, mode):
    monkeypatch.setattr(ocr, "poppler_available", lambda: True)
    paths = []

    def run(args, **kwargs):
        if args[0] == "pdfinfo":
            paths.append(Path(args[1]).parent)
            return SimpleNamespace(returncode=0, stdout="Pages: 1")
        if mode == "timeout":
            raise subprocess.TimeoutExpired(args, 30)
        if mode == "missing":
            raise FileNotFoundError("synthetic missing converter")
        return SimpleNamespace(
            returncode=0 if mode == "no-output" else 1,
            stderr=b"bad PDF " * 100 if mode == "exit" else b"",
        )

    monkeypatch.setattr(ocr.subprocess, "run", run)
    with pytest.raises(ValueError) as exc:
        ocr.rasterize_pdf(b"synthetic input")
    assert len(str(exc.value)) < 400
    assert paths and all(not path.exists() for path in paths)


def test_missing_converter_does_not_start_process(monkeypatch):
    monkeypatch.setattr(ocr, "poppler_available", lambda: False)

    def forbidden(*args, **kwargs):
        pytest.fail("Converter must not start when unavailable")

    monkeypatch.setattr(ocr.subprocess, "run", forbidden)
    with pytest.raises(ValueError, match="PDF scanning"):
        ocr.rasterize_pdf(b"synthetic input")
