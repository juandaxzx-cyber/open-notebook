"""Entrypoint: `uv run python -m tutor` (serves on TUTOR_HOST:TUTOR_PORT)."""

import uvicorn

from tutor.app import create_app
from tutor.config import TutorSettings


def main() -> None:
    settings = TutorSettings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
