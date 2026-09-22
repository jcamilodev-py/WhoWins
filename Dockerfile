# The builder resolves and installs; the final image carries only the virtual
# environment and the code, without uv or build leftovers.
FROM ghcr.io/astral-sh/uv:0.10.6 AS uv

FROM python:3.14-slim-trixie AS builder
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies before the code: they change far less often, so this layer stays cached.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-cache
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

FROM python:3.14-slim-trixie
RUN useradd --system --create-home --uid 10001 whowins
WORKDIR /app
COPY --from=builder --chown=whowins:whowins /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    # Render's proxy terminates TLS, and its address is not known in advance.
    # Trusting it is what makes the scheme https and the client IP the real
    # one, which the rate limiter keys on.
    FORWARDED_ALLOW_IPS="*"
USER whowins
EXPOSE 10000
# Migrations run on start because Render's pre-deploy command is paid-only.
# One process on purpose: the rate limits live in its memory.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
