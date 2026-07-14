from fastapi.testclient import TestClient

from tutor.app import create_app
from tutor.config import TutorSettings


def test_root_serves_chat_page() -> None:
    app = create_app(settings=TutorSettings())
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert "Atenea" in body
    assert "/session" in body  # talks to the session endpoints


def test_chat_page_has_unified_nav_and_markdown() -> None:
    body = TestClient(create_app(settings=TutorSettings())).get("/").text
    assert "notebooks-link" in body  # single entry point: link out to OpenNotebook
    assert "/config" in body  # nav target comes from the service, not hardcoded
    assert "renderMarkdown" in body  # tutor replies render as markdown


def test_config_returns_default_notebook_ui_url() -> None:
    response = TestClient(create_app(settings=TutorSettings())).get("/config")
    assert response.status_code == 200
    assert response.json() == {"notebook_ui_url": "http://localhost:8502"}


def test_config_reflects_settings_override() -> None:
    settings = TutorSettings(notebook_ui_url="http://elsewhere:9000")
    response = TestClient(create_app(settings=settings)).get("/config")
    assert response.json()["notebook_ui_url"] == "http://elsewhere:9000"


def test_chat_page_strips_task_markers_client_side() -> None:
    # BUG 3 / belt-and-braces for BUG 1: the UI defensively removes any
    # [[TASK: ...]] marker before rendering a tutor bubble.
    body = TestClient(create_app(settings=TutorSettings())).get("/").text
    assert "stripTaskMarkers" in body


def test_notebooks_link_advertises_its_target() -> None:
    # BUG 4: the header link exposes where it points via its title attribute,
    # so an unreachable OpenNotebook reads as environmental, not a broken link.
    body = TestClient(create_app(settings=TutorSettings())).get("/").text
    assert "link.title" in body
