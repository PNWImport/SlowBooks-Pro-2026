"""User-uploaded SVGs need a policy stricter than the application's JS UI."""

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.main import security_headers


@pytest.mark.parametrize(
    "path",
    ["/static/uploads/company_logo.svg", "/static//uploads/company_logo.svg"],
)
@pytest.mark.parametrize("status", [200, 304])
def test_uploaded_svg_disables_active_content(path, status):
    import asyncio

    async def check():
        request = Request({"type": "http", "path": path, "headers": []})

        async def serve(request):
            if status == 304:
                return Response(status_code=304)
            return Response("<svg/>", media_type="image/svg+xml")

        response = await security_headers(request, serve)
        policy = response.headers["Content-Security-Policy"]
        assert "sandbox;" in policy
        assert "default-src 'none'" in policy
        assert "script-src 'none'" in policy
        assert "allow-scripts" not in policy
        assert "allow-same-origin" not in policy

    asyncio.run(check())
