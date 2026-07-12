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
