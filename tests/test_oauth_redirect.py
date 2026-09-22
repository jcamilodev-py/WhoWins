"""Where Google sends the user back.

Google itself is replaced: the authorize step would otherwise fetch its
discovery document over the network.
"""

import pytest
from fastapi.responses import RedirectResponse
from httpx import AsyncClient

from app.auth.oauth2_router import oauth
from app.core.settings import settings


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    seen: dict[str, str] = {}

    async def fake_authorize_redirect(request, redirect_uri):
        seen["redirect_uri"] = redirect_uri
        return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth")

    monkeypatch.setattr(oauth.google, "authorize_redirect", fake_authorize_redirect)
    return seen


async def test_google_callback_is_derived_from_the_request_by_default(
    client: AsyncClient, captured: dict[str, str], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "oauth_redirect_base_url", None)

    await client.get("/oauth2/authorization/google")

    assert captured["redirect_uri"] == "http://test/login/oauth2/code/google"


async def test_google_callback_goes_through_the_public_address_when_set(
    client: AsyncClient, captured: dict[str, str], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "oauth_redirect_base_url", "https://whowins.onrender.com/")

    await client.get("/oauth2/authorization/google")

    assert captured["redirect_uri"] == "https://whowins.onrender.com/login/oauth2/code/google"
