import logging
from urllib.parse import urlencode

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.auth.service import AuthService
from app.core.database import DBSession
from app.core.settings import settings
from app.user.repository import UserRepository

logger = logging.getLogger(__name__)

oauth = OAuth()
oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=settings.google_client_id,
    client_secret=settings.google_client_secret,
    client_kwargs={"scope": "openid email profile"},
)

router = APIRouter(tags=["oauth2"])

auth_service = AuthService(UserRepository())


def _login_error_redirect(reason: str) -> RedirectResponse:
    query = urlencode({"error": reason})
    return RedirectResponse(f"{settings.frontend_url}/login?{query}")


@router.get("/oauth2/authorization/google")
async def google_authorize(request: Request):
    redirect_uri = request.url_for("google_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/login/oauth2/code/google", name="google_callback")
async def google_callback(request: Request, db: DBSession):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError:
        logger.warning("Google OAuth callback failed", exc_info=True)
        return _login_error_redirect("oauth_failed")

    userinfo = token.get("userinfo") or {}

    email = userinfo.get("email")
    google_id = userinfo.get("sub")
    if not email or not google_id:
        return _login_error_redirect("oauth_failed")

    # Sin esta comprobacion, una cuenta de Google con un email sin verificar
    # podria vincularse a una cuenta local existente y apropiarsela.
    if not userinfo.get("email_verified"):
        return _login_error_redirect("email_not_verified")

    # La sesión viaja entera en las cookies httpOnly que pone _issue_tokens
    response = RedirectResponse(f"{settings.frontend_url}/")
    await auth_service.login_with_google(db, email, google_id, userinfo.get("name"), response)

    return response
