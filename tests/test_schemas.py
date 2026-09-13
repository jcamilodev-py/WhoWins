import uuid

import pytest
from pydantic import ValidationError

from app.auth.schemas import RegisterRequest, UserPublic
from app.user.models import Role


def test_register_request_valid_data():

    data = {"email": "user@example.com", "password": "password123"}
    request = RegisterRequest(**data)

    assert request.email == "user@example.com"
    assert request.password == "password123"


def test_register_request_invalid_email_raises_validation_error():
    invalid_data = {"email": "invalid-email", "password": "password123"}

    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest(**invalid_data)
    assert "email" in str(exc_info.value)


def test_register_request_short_password_raises_validation_error():

    short_pwd_data = {"email": "test@example.com", "password": "123"}

    with pytest.raises(ValidationError) as exc_info:
        RegisterRequest(**short_pwd_data)

    assert "password" in str(exc_info.value)


def test_user_public_from_attributes():
    class MockUser:
        id = uuid.uuid4()
        email = "admin@example.com"
        role = Role.ADMIN

    mock = MockUser()
    public = UserPublic.model_validate(mock)

    assert public.id == mock.id
    assert public.email == mock.email
    assert public.role == Role.ADMIN


def test_user_update_me_valid_timezone():
    from app.user.schemas import UserUpdateMe

    schema = UserUpdateMe(timezone="America/Bogota")
    assert schema.timezone == "America/Bogota"


def test_user_update_me_invalid_timezone_raises_error():
    from app.user.schemas import UserUpdateMe

    with pytest.raises(ValidationError) as exc_info:
        UserUpdateMe(timezone="Invalid/Zone")
    assert "Invalid IANA timezone identifier" in str(exc_info.value)
