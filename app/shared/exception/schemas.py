from datetime import datetime

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    timestamp: datetime
    status: int
    error: str
    message: str
    path: str
