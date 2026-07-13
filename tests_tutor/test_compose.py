"""Guard the tutor service wiring in docker-compose.yml (PR-DX1).

Parses the compose file directly so drift is caught by ``make check-tutor``
without requiring Docker in CI. PyYAML is guaranteed in the dev environment
(a locked transitive dependency of the project).
"""

from pathlib import Path
from typing import Any

import yaml

_COMPOSE_PATH = Path(__file__).resolve().parent.parent / "docker-compose.yml"


def _tutor_service() -> dict[str, Any]:
    compose = yaml.safe_load(_COMPOSE_PATH.read_text(encoding="utf-8"))
    services = compose["services"]
    assert "tutor" in services, "tutor service missing from docker-compose.yml"
    service: dict[str, Any] = services["tutor"]
    return service


def test_tutor_builds_from_dedicated_dockerfile() -> None:
    build = _tutor_service()["build"]
    assert build["dockerfile"] == "Dockerfile.tutor"
    assert (_COMPOSE_PATH.parent / "Dockerfile.tutor").is_file()


def test_tutor_exposes_default_port() -> None:
    assert "5056:5056" in _tutor_service()["ports"]


def test_tutor_targets_compose_service_names() -> None:
    env = dict(item.split("=", 1) for item in _tutor_service()["environment"])
    assert env["SURREAL_URL"] == "ws://surrealdb:8000/rpc"
    assert env["OPEN_NOTEBOOK_API_URL"] == "http://open_notebook:5055"


def test_tutor_reads_optional_env_file() -> None:
    assert _tutor_service()["env_file"] == [{"path": ".env", "required": False}]


def test_tutor_starts_after_its_dependencies() -> None:
    assert set(_tutor_service()["depends_on"]) == {"surrealdb", "open_notebook"}
