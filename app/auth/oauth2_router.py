from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.auth.service import AuthService
from app.user.repository import UserRepository
from app.core.database import DBSession
from app.core.settings import settings

oauth = OAuth()
oauth.register(name="google", server_metadata_url="https://accounts.google.com/.well-known/openid-configuration", client_id=settings.google_client_id, client_secret=settings.google_client_secret, client_kwargs={"scope": "openid email profile"})

router = APIRouter(tags=["oauth2"])

auth_service = AuthService(UserRepository())


@router.get("/oauth2/authorization/google")
async def google_authorize(request: Request):
    redirect_uri = request.url_for("google_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/login/oauth2/code/google", name="google_callback")
async def google_callback(request: Request, db: DBSession):
    token = await oauth.google.authorize_access_token(request)
    userinfo = token["userinfo"]

    email = userinfo["email"]
    google_id = userinfo["sub"]

    # The session is carried entirely by the httpOnly cookies _issue_tokens sets
    response = RedirectResponse(f"{settings.frontend_url}/")
    await auth_service.login_with_google(db, email, google_id, response)

    return response