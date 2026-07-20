import pytest

from tutor.config import TutorSettings


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "TUTOR_HOST",
        "TUTOR_PORT",
        "OPEN_NOTEBOOK_API_URL",
        "OPEN_NOTEBOOK_PASSWORD",
    ):
        monkeypatch.delenv(var, raising=False)
    settings = TutorSettings.from_env()
    assert settings.host == "0.0.0.0"
    assert settings.port == 5056
    assert settings.open_notebook_api_url == "http://localhost:5055"
    assert settings.open_notebook_password is None


def test_from_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUTOR_HOST", "127.0.0.1")
    monkeypatch.setenv("TUTOR_PORT", "6001")
    monkeypatch.setenv("OPEN_NOTEBOOK_API_URL", "http://open-notebook:5055")
    monkeypatch.setenv("OPEN_NOTEBOOK_PASSWORD", "secret")
    settings = TutorSettings.from_env()
    assert settings.host == "127.0.0.1"
    assert settings.port == 6001
    assert settings.open_notebook_api_url == "http://open-notebook:5055"
    assert settings.open_notebook_password == "secret"


def test_review_horizon_days_defaults_to_sixty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TUTOR_REVIEW_HORIZON_DAYS", raising=False)
    assert TutorSettings.from_env().review_horizon_days == 60.0


def test_review_horizon_days_reads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUTOR_REVIEW_HORIZON_DAYS", "45")
    assert TutorSettings.from_env().review_horizon_days == 45.0


# --- PR-W1: per-turn verification settings ---


def test_verify_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "TUTOR_VERIFY_TURNS",
        "TUTOR_VERIFY_PROFILE",
        "TUTOR_GROUNDING_BUDGET_TOKENS",
    ):
        monkeypatch.delenv(var, raising=False)
    settings = TutorSettings.from_env()
    assert settings.verify_turns == "grounded"
    assert settings.verify_profile == "high"
    assert settings.grounding_budget_tokens == 16000


def test_verify_reads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUTOR_VERIFY_TURNS", "all")
    monkeypatch.setenv("TUTOR_VERIFY_PROFILE", "cheap")
    monkeypatch.setenv("TUTOR_GROUNDING_BUDGET_TOKENS", "4000")
    settings = TutorSettings.from_env()
    assert settings.verify_turns == "all"
    assert settings.verify_profile == "cheap"
    assert settings.grounding_budget_tokens == 4000


def test_verify_turns_rejects_unknown_scope() -> None:
    with pytest.raises(Exception):  # pydantic ValidationError
        TutorSettings(verify_turns="sometimes")  # type: ignore[arg-type]
