from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.settings import settings

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.rate_limit_storage_uri)
