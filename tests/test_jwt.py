from datetime import datetime, timezone
import pytest
import jwt

from app.auth.jwt_handler import create_access_token, create_refresh_token, decode_token
from app.core.settings import settings


def test_create_and_decode_access_token():
    user_email = "testuser@example.com"
    token_version = 2

    token = create_access_token({"sub": user_email, "tv": token_version})
    assert isinstance(token, str)

    payload = decode_token(token)

    assert payload["sub"] == user_email
    assert payload["type"] == "access"
    assert payload["tv"] == token_version

    assert "exp" in payload
    exp_timestamp = payload["exp"]
    current_timestamp = datetime.now(timezone.utc).timestamp()
    assert exp_timestamp > current_timestamp


def test_create_and_decode_refresh_token():

    user_email = "refreshtest@example.com"

    token = create_refresh_token({"sub": user_email, "tv": 0})
    payload = decode_token(token)

    assert payload["sub"] == user_email
    assert payload["type"] == "refresh"
    assert payload["tv"] == 0


def test_decode_invalid_token_raises_error():
    corrupt_token = "this.is.not.a.valid.jwt"

    with pytest.raises(jwt.PyJWTError):
        decode_token(corrupt_token)
