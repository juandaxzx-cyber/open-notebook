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


def test_chat_page_has_upload_affordance_and_privado_badge() -> None:
    # PR-BT3: upload affordance (file/url/text tabs) in the source picker,
    # gated by grounding_enabled like the picker itself, plus the "privado"
    # badge suffix rendered for the requester's own private uploads.
    body = TestClient(create_app(settings=TutorSettings())).get("/").text
    assert 'id="upload-toggle"' in body
    assert 'id="upload-panel"' in body
    assert 'data-utab="file"' in body
    assert 'data-utab="url"' in body
    assert 'data-utab="text"' in body
    assert "/sources/upload" in body
    assert "/sources/create" in body
    assert "privado" in body  # badge suffix in loadSources


def test_chat_page_has_welcome_panel() -> None:
    # PR-F4: brief Spanish welcome on first contact (magic-link landing or a
    # fresh, undismissed browser) -- dismissible, shown once via a
    # localStorage flag, reopenable through the "Ayuda" nav item.
    body = TestClient(create_app(settings=TutorSettings())).get("/").text
    assert 'id="welcome"' in body
    assert 'id="welcome-dismiss"' in body
    assert 'id="help-link"' in body
    assert "atenea_welcome_seen" in body
    assert "maybeShowWelcome" in body
    assert (
        "perfil" in body.lower()
        and "material" in body.lower()
        and "sesi" in body.lower()
    )


def test_chat_page_has_empty_state_hints() -> None:
    # PR-F4: fresh account -- sessions list and source picker get a one-line
    # guiding hint instead of a blank panel (Historial/Tu progreso already
    # carried hints from F3/G2; locked here too for completeness).
    body = TestClient(create_app(settings=TutorSettings())).get("/").text
    assert 'id="source-hint"' in body
    assert 'id="sessions-hint"' in body
    assert "Aún no hay sesiones." in body  # Historial empty state (pre-existing)
    assert (
        "Aún no hay progreso registrado" in body
    )  # Tu progreso empty state (pre-existing)


def test_chat_page_has_verification_wait_phase() -> None:
    # PR-F4: the typing indicator gains a "Verificando..." phase during a
    # gated grounded turn, so latency reads as care, not a hang. Gated on
    # session grounded-ness (client state) + /config's verify_turns.
    body = TestClient(create_app(settings=TutorSettings())).get("/").text
    assert "Verificando con tu fuente" in body
    assert "sessionGrounded" in body
    assert "showVerifyPhase" in body


def test_chat_page_has_subtle_outcome_chips() -> None:
    # PR-F4: corrected/escalated verification outcomes get a subtle,
    # non-alarming chip alongside the existing flagged/limits-admitted
    # notices -- honest visibility that the gate is working.
    body = TestClient(create_app(settings=TutorSettings())).get("/").text
    assert "VERIFY_OUTCOME_CHIP" in body
    assert "verify-outcome" in body
    assert "corrected" in body
    assert "escalated" in body


def test_chat_page_has_upload_polling_and_reset() -> None:
    # PR-F4: after a successful upload, poll the picker a few bounded times
    # while OpenNotebook processes it async, then a "still processing" state
    # if it never shows up; fields reset after a successful submit.
    body = TestClient(create_app(settings=TutorSettings())).get("/").text
    assert "pollForNewSource" in body
    assert "resetUploadFields" in body
    assert "Sigue procesándose" in body


def test_chat_page_has_distinct_cap_state() -> None:
    # PR-F4: the daily cap (429, PR-BT2) renders as its own friendly state,
    # not the generic red error line.
    body = TestClient(create_app(settings=TutorSettings())).get("/").text
    assert "addCapNotice" in body
    assert "cap-notice" in body
    assert "429" in body


def test_chat_page_has_viewport_meta() -> None:
    # PR-F4: mobile pass precondition -- the viewport meta tag must exist
    # (it already did; locked here so a future edit can't silently drop it).
    body = TestClient(create_app(settings=TutorSettings())).get("/").text
    assert (
        '<meta name="viewport" content="width=device-width, initial-scale=1">' in body
    )


def test_chat_page_has_mobile_touch_targets() -> None:
    # PR-F4: mobile pass -- interactive controls (nav links, buttons, tabs,
    # list rows, the source select) get a >=44px touch target at narrow
    # viewports (Apple HIG), reasoned via CSS since this sandbox can't
    # render pages.
    body = TestClient(create_app(settings=TutorSettings())).get("/").text
    assert "min-height: 44px" in body
