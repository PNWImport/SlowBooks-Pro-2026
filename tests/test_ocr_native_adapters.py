"""Native bridge contract tests with synthetic modules, not hardware acceptance."""

import sys
from types import ModuleType, SimpleNamespace as Obj

import pytest

from app.services import ocr_engines as ocr


def install_module(monkeypatch, name, **attributes):
    pieces = name.split(".")
    for count in range(1, len(pieces) + 1):
        path = ".".join(pieces[:count])
        if path not in sys.modules:
            module = ModuleType(path)
            module.__path__ = []
            monkeypatch.setitem(sys.modules, path, module)
    module = sys.modules[name]
    for key, value in attributes.items():
        monkeypatch.setattr(module, key, value, raising=False)
    return module


@pytest.fixture
def vision_bridge(monkeypatch):
    state = {
        "source": object(),
        "image": object(),
        "ok": True,
        "observations": [],
        "languages": ["en-US"],
    }

    class Request:
        @classmethod
        def alloc(cls):
            return cls()

        def init(self):
            return self

        def supportedRecognitionLanguagesAndReturnError_(self, error):
            if isinstance(state["languages"], Exception):
                raise state["languages"]
            return state["languages"], None

        def setRecognitionLevel_(self, level):
            assert level == 0

        def setUsesLanguageCorrection_(self, enabled):
            assert enabled is False

        def results(self):
            return state["observations"]

    class Handler:
        @classmethod
        def alloc(cls):
            return cls()

        def initWithCGImage_options_(self, image, options):
            assert image is state["image"]
            return self

        def performRequests_error_(self, requests, error):
            assert len(requests) == 1
            return state["ok"], None

    install_module(
        monkeypatch,
        "Quartz",
        CGImageSourceCreateWithData=lambda data, options: state["source"],
        CGImageSourceCreateImageAtIndex=lambda source, index, options: state["image"],
        CGImageGetWidth=lambda image: 100,
        CGImageGetHeight=lambda image: 200,
    )
    install_module(
        monkeypatch,
        "Vision",
        VNRecognizeTextRequest=Request,
        VNImageRequestHandler=Handler,
    )
    monkeypatch.setattr(ocr, "sys", Obj(platform="darwin"))
    return state


def observation(text, y, corners=True):
    class Observation:
        def topCandidates_(self, count):
            return [Obj(string=lambda: text, confidence=lambda: 0.9)] if text else []

        def boundingBox(self):
            return Obj(origin=Obj(x=0.25, y=y), size=Obj(width=0.5, height=0.25))

        def topLeft(self):
            if not corners:
                raise AttributeError("synthetic legacy observation without corners")
            return Obj(x=0.25, y=y + 0.25)

        def topRight(self):
            return Obj(x=0.75, y=y + 0.25)

    return Observation()


def test_vision_geometry_confidence_and_reading_order(vision_bridge):
    vision_bridge["observations"] = [
        observation("", 0),
        observation("World", 0, corners=False),
        observation("Hello", 0.5),
    ]
    engine = ocr.VisionEngine()
    assert engine.available() and engine.unavailable_reason() is None
    result = engine.recognize(b"synthetic-image", "en-US")
    assert result.text == "Hello\nWorld"
    assert result.engine == "vision" and result.language == "en-US"
    first, second = result.words
    assert (first.left, first.top, first.width, first.height, first.conf) == (
        25,
        50,
        50,
        50,
        90,
    )
    assert first.slope == 0 and second.slope is None


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("source", None, "decode"),
        ("image", None, "decode"),
        ("ok", False, "recognition failed"),
    ],
)
def test_vision_decode_and_recognition_failures(vision_bridge, field, value, message):
    vision_bridge[field] = value
    with pytest.raises(ocr.ocr_service.OCRRuntimeError, match=message):
        ocr.VisionEngine().recognize(b"synthetic-image")


@pytest.mark.parametrize(
    "languages", [[], RuntimeError("synthetic language probe failure")]
)
def test_vision_language_probe_failure_does_not_disable_recognition(
    vision_bridge, languages
):
    vision_bridge["languages"] = languages
    assert ocr.VisionEngine().info() == {
        "available": True,
        "version": "macOS Vision",
        "languages": None,
    }


@pytest.mark.parametrize(
    "engine,platform", [(ocr.VisionEngine, "darwin"), (ocr.WinRTEngine, "win32")]
)
def test_missing_native_bridge_is_unavailable(monkeypatch, engine, platform):
    monkeypatch.setattr(ocr, "sys", Obj(platform=platform))

    def missing(self):
        raise ImportError("synthetic missing bridge")

    monkeypatch.setattr(engine, "_bridge", missing)
    instance = engine()
    assert not instance.available()
    assert instance.unavailable_reason() == ocr.NATIVE_MISSING_MESSAGE


@pytest.mark.parametrize("prefix", ["winrt", "winsdk"])
def test_windows_projection_import_paths(monkeypatch, prefix):
    if prefix == "winsdk":
        monkeypatch.setitem(sys.modules, "winrt.windows.graphics.imaging", None)
    decoder, engine, writer, stream = object(), object(), object(), object()
    install_module(
        monkeypatch, f"{prefix}.windows.graphics.imaging", BitmapDecoder=decoder
    )
    install_module(monkeypatch, f"{prefix}.windows.media.ocr", OcrEngine=engine)
    install_module(
        monkeypatch,
        f"{prefix}.windows.storage.streams",
        DataWriter=writer,
        InMemoryRandomAccessStream=stream,
    )
    assert ocr.WinRTEngine()._bridge() == (decoder, engine, writer, stream)


@pytest.mark.parametrize("fails", [False, True])
def test_windows_apartment_initialization(monkeypatch, fails):
    calls = []

    def initialize(apartment):
        calls.append(apartment)
        if fails:
            raise RuntimeError("synthetic already initialized")

    install_module(
        monkeypatch,
        "winrt.runtime",
        ApartmentType=Obj(MULTI_THREADED="MTA"),
        init_apartment=initialize,
    )
    monkeypatch.setattr(ocr, "_winrt_thread_ident", None)
    ocr._winrt_thread_init()
    assert calls == ["MTA"]
    assert ocr._on_winrt_thread(lambda: "inline") == "inline"


def test_windows_missing_language_is_unavailable(monkeypatch):
    engine = ocr.WinRTEngine()
    monkeypatch.setattr(ocr, "sys", Obj(platform="win32"))
    monkeypatch.setattr(
        engine,
        "_bridge",
        lambda: (
            None,
            Obj(try_create_from_user_profile_languages=lambda: None),
            None,
            None,
        ),
    )
    assert not engine.available()
    assert engine.unavailable_reason() == ocr.NATIVE_MISSING_MESSAGE


def test_tesseract_without_language_data_is_unavailable(monkeypatch):
    monkeypatch.setattr(ocr.ocr_service, "tesseract_available", lambda: True)
    monkeypatch.setattr(ocr.ocr_service, "ocr_language", lambda: None)
    engine = ocr.TesseractEngine()
    assert engine.unavailable_reason() == ocr.LANGUAGE_DATA_MESSAGE
    with pytest.raises(ocr.EngineUnavailable, match="language data"):
        engine.recognize(b"synthetic")


def test_windows_words_retain_line_slope():
    result = Obj(
        lines=[
            Obj(
                words=[
                    Obj(text="TOTAL", bounding_rect=Obj(x=0, y=0, width=20, height=10)),
                    Obj(
                        text="12.34", bounding_rect=Obj(x=100, y=4, width=20, height=10)
                    ),
                ]
            )
        ]
    )
    words = ocr._winrt_words(result)
    assert [word.slope for word in words] == [0.04, 0.04]
    assert ocr.lines_from_words(words) == "TOTAL 12.34"


def test_platform_selection_and_native_preference(monkeypatch, vision_bridge):
    monkeypatch.setenv("SLOWBOOKS_OCR_ENGINE", "auto")
    assert isinstance(ocr._native_engine_for_platform(), ocr.VisionEngine)
    assert isinstance(ocr.get_engine(), ocr.VisionEngine)
    monkeypatch.setattr(ocr, "sys", Obj(platform="win32"))
    assert isinstance(ocr._native_engine_for_platform(), ocr.WinRTEngine)
    monkeypatch.setattr(ocr, "sys", Obj(platform="linux"))
    assert ocr._native_engine_for_platform() is None
    assert not ocr.WinRTEngine().info()["available"]
    assert not ocr.VisionEngine().info()["available"]


def test_windows_recognition_without_language_fails_cleanly(monkeypatch):
    class Decoder:
        @staticmethod
        async def create_async(stream):
            return Decoder()

        async def get_software_bitmap_async(self):
            return "synthetic-bitmap"

    class Writer:
        def __init__(self, output):
            pass

        def write_bytes(self, data):
            assert data == b"synthetic"

        async def store_async(self):
            return None

    engine = ocr.WinRTEngine()
    monkeypatch.setattr(
        engine,
        "_bridge",
        lambda: (
            Decoder,
            Obj(try_create_from_user_profile_languages=lambda: None),
            Writer,
            lambda: Obj(get_output_stream_at=lambda position: None),
        ),
    )
    with pytest.raises(ocr.EngineUnavailable, match="No OCR language"):
        engine.recognize(b"synthetic")
