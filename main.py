import uvicorn

from app.core.settings import settings


def main() -> None:
    uvicorn.run(
        "app.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=settings.is_dev,
    )


if __name__ == "__main__":
    main()
