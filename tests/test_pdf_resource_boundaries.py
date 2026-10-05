"""PDF resource helpers reject files outside the upload root without reading."""

from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.services import pdf_service


@pytest.mark.parametrize(
    "url",
    [
        "file:///synthetic/private",
        "https://example.invalid/image",
        "http://127.0.0.1/image",
        "relative.png",
    ],
)
def test_external_resources_rejected_without_fetch(monkeypatch, url):
    from weasyprint import URLFetcher

    fetch = Mock(side_effect=AssertionError("external resource fetched"))
    monkeypatch.setattr(URLFetcher, "fetch", fetch)
    with pytest.raises(ValueError, match="URL scheme not allowed"):
        pdf_service._safe_url_fetcher(url)
    fetch.assert_not_called()


@pytest.mark.parametrize("settings", [None, {}, {"company_logo_path": ""}])
def test_missing_logo(settings):
    assert pdf_service._company_logo_data_uri(settings) == ""


@pytest.mark.parametrize(
    "stored, exists",
    [
        ("/static/uploads/../../private.png", True),
        ("/static/uploads/missing.png", False),
        ("/static/uploads/not_image.txt", True),
        ("/static/uploads/unknown", True),
    ],
)
def test_rejected_logo_is_never_read(tmp_path, monkeypatch, stored, exists):
    monkeypatch.setattr(
        pdf_service.storage, "uploads_root", lambda: tmp_path / "uploads"
    )
    monkeypatch.setattr(Path, "is_file", lambda self: exists)
    read = Mock(side_effect=AssertionError("rejected file was read"))
    monkeypatch.setattr(Path, "read_bytes", read)
    assert pdf_service._company_logo_data_uri({"company_logo_path": stored}) == ""
    read.assert_not_called()


def test_unreadable_logo_is_omitted(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pdf_service.storage, "uploads_root", lambda: tmp_path / "uploads"
    )
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(Path, "read_bytes", Mock(side_effect=OSError("unreadable")))
    assert (
        pdf_service._company_logo_data_uri(
            {"company_logo_path": "/static/uploads/logo.png"}
        )
        == ""
    )


@pytest.mark.parametrize(
    "value, expected",
    [(None, "$0.00"), ("invalid", "$0.00"), ({}, "$0.00"), ("1234.5", "$1,234.50")],
)
def test_currency_filter(value, expected):
    assert pdf_service._format_currency(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [(None, ""), (date(2026, 9, 8), "Sep 08, 2026"), ("synthetic", "synthetic")],
)
def test_date_filter(value, expected):
    assert pdf_service._format_date(value) == expected


def test_data_resource_fetch_preserves_headers_and_protocol_gate(monkeypatch):
    from weasyprint import URLFetcher

    response = object()
    fetch = Mock(return_value=response)
    monkeypatch.setattr(URLFetcher, "fetch", fetch)
    fetcher = pdf_service._safe_url_fetcher
    headers = {"Accept": "text/plain"}
    assert fetcher.fetch("data:text/plain,synthetic", headers=headers) is response
    assert fetcher._allowed_protocols == ("data",)
    fetch.assert_called_once_with("data:text/plain,synthetic", headers=headers)


@pytest.mark.parametrize(
    "kind", ["estimate", "statement", "analytics", "collection", "check"]
)
def test_pdf_wrappers_preserve_context_and_use_shared_renderer(monkeypatch, kind):
    template = Mock()
    template.render.return_value = "synthetic html"
    lookup = Mock(return_value=template)
    renderer = Mock(return_value=b"synthetic pdf")
    monkeypatch.setattr(pdf_service._jinja_env, "get_template", lookup)
    monkeypatch.setattr(pdf_service, "render_pdf", renderer)
    company = {"company_name": "Synthetic company"}
    subject = object()
    if kind == "estimate":
        result = pdf_service.generate_estimate_pdf(subject, company)
        name = "estimate_pdf.html"
        assert template.render.call_args.kwargs["est"] is subject
    elif kind == "statement":
        result = pdf_service.generate_statement_pdf(
            subject, [], [], company, date(2026, 9, 8)
        )
        name = "statement_pdf.html"
        assert template.render.call_args.kwargs["as_of_date"] == date(2026, 9, 8)
    elif kind == "analytics":
        result = pdf_service.generate_analytics_pdf({}, {"year": 2026}, company)
        name = "analytics_pdf.html"
        assert template.render.call_args.kwargs["company_logo_data_uri"] == ""
    elif kind == "collection":
        result = pdf_service.generate_collection_letter_pdf(
            subject, [], company, "reminder", 25
        )
        name = "collection_letter.html"
        assert template.render.call_args.kwargs["total_due"] == 25
        assert template.render.call_args.kwargs["letter_type"] == "reminder"
    else:
        result = pdf_service.generate_check_pdf({"amount": "1.995"}, company)
        name = "check_pdf.html"
        assert (
            template.render.call_args.kwargs["check"]["amount_words"]
            == "Two and 00/100"
        )
    assert result == b"synthetic pdf"
    lookup.assert_called_once_with(name)
    assert template.render.call_args.kwargs["company"] is company
    renderer.assert_called_once_with("synthetic html")
