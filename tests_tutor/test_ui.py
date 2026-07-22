from collections.abc import Sequence

from fastapi.testclient import TestClient

from tutor.app import create_app
from tutor.config import TutorSettings
from tutor.llm.interface import ChatMessage, ChatResponse
from tutor.session.engine import TutorEngine
from tutor.session.store import SessionStore
from tutor.tools.registry import ToolRegistry


class _UnusedLLM:
    """/config never touches the engine — this just satisfies create_app's
    eager engine construction without pulling in the real esperanto client."""

    async def complete(self, messages: Sequence[ChatMessage]) -> ChatResponse:
        raise AssertionError("not expected to be called in these tests")


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
    assert response.json() == {
        "notebook_ui_url": "http://localhost:8502",
        "grounding_enabled": False,
        "llm_provider": None,
        "llm_model": None,
        "verify_turns": "grounded",  # PR-W1 default
        "verify_profile": "high",
    }


def test_config_reflects_settings_override() -> None:
    settings = TutorSettings(notebook_ui_url="http://elsewhere:9000")
    response = TestClient(create_app(settings=settings)).get("/config")
    assert response.json()["notebook_ui_url"] == "http://elsewhere:9000"


def test_config_exposes_grounding_flag_and_provider_visibility() -> None:
    # PR-F3: the picker and the header chip both key off /config, never a
    # hardcoded default — and never a secret (no API key field exists here).
    settings = TutorSettings(
        grounding_enabled=True, llm_provider="anthropic", llm_model="claude-x"
    )
    engine = TutorEngine(
        llm=_UnusedLLM(),
        registry=ToolRegistry(),
        store=SessionStore(),
        user_id="juanda",
    )
    body = (
        TestClient(create_app(settings=settings, engine=engine)).get("/config").json()
    )
    assert body["grounding_enabled"] is True
    assert body["llm_provider"] == "anthropic"
    assert body["llm_model"] == "claude-x"
    assert "api_key" not in body and "password" not in body


def test_config_defaults_grounding_off_and_provider_null() -> None:
    body = TestClient(create_app(settings=TutorSettings())).get("/config").json()
    assert body["grounding_enabled"] is False
    assert body["llm_provider"] is None
    assert body["llm_model"] is None


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


def test_chat_page_has_profile_questionnaire_hooks() -> None:
    # PR-F3: the in-page questionnaire (409 onboarding + "Perfil" nav edit)
    # mirrors ProfileIn exactly — one input per field, plus the retry seam.
    body = TestClient(create_app(settings=TutorSettings())).get("/").text
    assert 'id="profile-form"' in body
    assert 'id="profile-goal"' in body
    assert 'id="profile-level"' in body
    assert 'id="profile-hours"' in body
    assert 'id="profile-formats"' in body
    assert 'id="profile-link"' in body  # header nav item, pre-fills from GET /profile
    assert "openProfileOnboarding" in body  # seamless retry after 409
    assert "/profile" in body


def test_chat_page_has_provider_chip_and_grounding_gate() -> None:
    # PR-F3: provider/model visibility chip, and the source picker keyed off
    # /config's grounding_enabled flag (hidden entirely when off).
    body = TestClient(create_app(settings=TutorSettings())).get("/").text
    assert 'id="llm-chip"' in body
    assert "grounding_enabled" in body
    assert "/sources" in body
