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
    grounding_enabled: bool = False
    memory_enabled: bool = True
    verifier_provider: str | None = None
    verifier_model: str | None = None
    review_horizon_days: float = 60.0

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
        biased). TUTOR_GROUNDING_ENABLED opts into PR-M1 material grounding
        (default off; set 1/true to anchor sessions to a chosen source).
        TUTOR_MEMORY_ENABLED opts into PR-G2 consolidated learner memory
        (default ON; set 0/false to disable as a debug off-switch).
        TUTOR_VERIFIER_PROVIDER / TUTOR_VERIFIER_MODEL select the LLM that
        claim-checks each consolidated memory note before it is persisted
        (PR-G2); unset ⇒ falls back to the tutor's own provider/model (the
        engine warns when verifier == generator, same pattern as the eval
        judge in PR-E2). TUTOR_REVIEW_HORIZON_DAYS (PR-G3, default 60) is
        the SM-2 forgetting horizon: a reviewed item leaves the review
        working-set once its next interval exceeds this many days.
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
            "grounding_enabled": "TUTOR_GROUNDING_ENABLED",
            "memory_enabled": "TUTOR_MEMORY_ENABLED",
            "verifier_provider": "TUTOR_VERIFIER_PROVIDER",
            "verifier_model": "TUTOR_VERIFIER_MODEL",
            "review_horizon_days": "TUTOR_REVIEW_HORIZON_DAYS",
        }
        for field, var in env_map.items():
            value = os.environ.get(var)
            if value:
                values[field] = value
        return cls.model_validate(values)
