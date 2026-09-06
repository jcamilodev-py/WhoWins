from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

from app.core.limiter import limiter
from app.core.settings import settings
from app.shared.exception.handlers import register_exception_handlers
from app.user.router import router as user_router
from app.auth.oauth2_router import router as oauth2_router
from app.auth.router import router as auth_router


app = FastAPI(title="whowins", version="1.0", description="whowins")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# authlib guarda el "state" del flujo OAuth en request.session, asi que este
# middleware es obligatorio para que el login con Google funcione.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_signing_key,
    max_age=settings.session_max_age_seconds,
    same_site="lax",
    https_only=not settings.is_dev,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(user_router)
app.include_router(oauth2_router)
app.include_router(auth_router)
