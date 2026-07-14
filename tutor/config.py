"""Configuration for the tutoring service.

All configuration comes from environment variables (AGENTS.md hard rule #4).
No value is ever hardcoded outside the defaults below.
"""

import os

from pydantic import BaseModel


class TutorSettings(BaseModel):
    """Runtime settings for the tutoring service."""

    host: str = "0.0.0.0"
    port: int = 5056
    open_notebook_api_url: str = "http://localhost:5055"
    open_notebook_password: str | None = None
    notebook_ui_url: str = "http://localhost:8502"
    llm_provider: str | None = None
    llm_model: str | None = None
    judge_provider: str | None = None
    judge_model: str | None = None

    @classmethod
    def from_env(cls) -> "TutorSettings":
        """Build settings from environment variables, falling back to defaults.

        Variables: TUTOR_HOST, TUTOR_PORT, OPEN_NOTEBOOK_API_URL,
        OPEN_NOTEBOOK_PASSWORD (same variable OpenNotebook's API uses for
        its Bearer auth; leave unset if OpenNotebook runs without a password),
        TUTOR_NOTEBOOK_UI_URL (where the chat page's "Notebooks" link points,
        PR-F2), TUTOR_LLM_PROVIDER, TUTOR_LLM_MODEL, and for the eval harness
        TUTOR_JUDGE_PROVIDER, TUTOR_JUDGE_MODEL (default: the tutor's own
        provider/model — the runner warns, since same-family judging is
        biased).
        """
        values: dict[str, str] = {}
        env_map = {
            "host": "TUTOR_HOST",
            "port": "TUTOR_PORT",
            "open_notebook_api_url": "OPEN_NOTEBOOK_API_URL",
            "open_notebook_password": "OPEN_NOTEBOOK_PASSWORD",
            "notebook_ui_url": "TUTOR_NOTEBOOK_UI_URL",
            "llm_provider": "TUTOR_LLM_PROVIDER",
            "llm_model": "TUTOR_LLM_MODEL",
            "judge_provider": "TUTOR_JUDGE_PROVIDER",
            "judge_model": "TUTOR_JUDGE_MODEL",
        }
        for field, var in env_map.items():
            value = os.environ.get(var)
            if value:
                values[field] = value
        return cls.model_validate(values)
