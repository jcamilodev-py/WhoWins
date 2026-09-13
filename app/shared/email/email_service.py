from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType

from app.core.settings import settings

_conf = ConnectionConfig(
    MAIL_USERNAME=settings.mail_username,
    MAIL_PASSWORD=settings.mail_password,  # type: ignore[arg-type]  # pydantic coerces str -> SecretStr
    MAIL_FROM=settings.mail_username,
    MAIL_PORT=587,
    MAIL_SERVER="smtp.gmail.com",
    MAIL_STARTTLS=True,
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=True,
)

_fastmail = FastMail(_conf)


async def send_password_reset_email(to_email: str, reset_token: str) -> None:
    body = (
        "You requested a password reset.\n\n"
        "Click the link below to reset your password (expires in 1 hour):\n\n"
        f"{settings.frontend_url}/reset-password?token={reset_token}\n\n"
        "If you didn't request this, please ignore this email."
    )
    message = MessageSchema(
        subject="Password Reset Request - whowins",
        recipients=[to_email],  # type: ignore[list-item]  # pydantic coerces str -> NameEmail
        body=body,
        subtype=MessageType.plain,
    )
    await _fastmail.send_message(message)
