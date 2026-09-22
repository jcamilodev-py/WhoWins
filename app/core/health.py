import asyncio
import logging

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.database import DBSession

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

# Render gives a check five seconds. Answering 503 in time says more than a
# timeout, and a database that is slow to connect must not hold the check open.
DATABASE_CHECK_TIMEOUT_SECONDS = 2


@router.get("/health")
async def health(db: DBSession, response: Response) -> dict[str, str]:
    """The hosting platform's check: a deploy only takes traffic once this passes."""
    try:
        async with asyncio.timeout(DATABASE_CHECK_TIMEOUT_SECONDS):
            await db.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Health check could not reach the database", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable"}
    return {"status": "ok"}
