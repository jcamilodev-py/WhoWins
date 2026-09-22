import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

from app.auth.oauth2_router import router as oauth2_router
from app.auth.router import router as auth_router
from app.challenge.router import router as challenge_router
from app.checkin.router import router as check_in_router
from app.core.health import router as health_router
from app.core.limiter import limiter
from app.core.settings import settings
from app.shared.exception.handlers import register_exception_handlers
from app.user.router import router as user_router

# In production the schema would hand anyone a map of every endpoint. The
# frontend generates its types from a local server instead.
app = FastAPI(
    title="whowins",
    version="1.0",
    description="whowins",
    docs_url="/docs" if settings.is_dev else None,
    redoc_url="/redoc" if settings.is_dev else None,
    openapi_url="/openapi.json" if settings.is_dev else None,
)


class _WithoutHealthChecks(logging.Filter):
    # The platform polls /health every few seconds; those lines would bury the real traffic.
    def filter(self, record: logging.LogRecord) -> bool:
        return " /health HTTP/" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(_WithoutHealthChecks())

app.state.limiter = limiter
# slowapi's handler predates Starlette's typed exception-handler signature.
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]


# authlib keeps the OAuth "state" in request.session, so Google login needs
# this middleware.
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

app.include_router(health_router)
app.include_router(user_router)
app.include_router(oauth2_router)
app.include_router(auth_router)
app.include_router(challenge_router)
app.include_router(check_in_router)
