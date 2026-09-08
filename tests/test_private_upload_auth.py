"""Attachments must not bypass login through the static-file mount."""

import pytest


@pytest.mark.parametrize(
    "path",
    [
        "/static/uploads/attachments/invoice/1/receipt.pdf",
        "/static/uploads/attachments",
        "/static/uploads/intake/pending.json",
        "/static//uploads/attachments/invoice/1/receipt.pdf",
        "/static/uploads/%61ttachments/invoice/1/receipt.pdf",
        "/static/uploads/other/%2e%2e/attachments/invoice/1/receipt.pdf",
    ],
)
def test_private_uploads_require_login(unauthed_client, path):
    assert unauthed_client.get(path).status_code == 401


def test_login_assets_stay_public(unauthed_client):
    assert unauthed_client.get("/static/css/style.css").status_code == 200
