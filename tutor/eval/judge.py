"""LLM judge: applies one rubric criterion per call (PR-E2).

Bias mitigations (docs/atenea/tutor_pedagogy_evidence.md): single-criterion
prompts, reference-anchored annotations from the persona script, explicit
anti-verbosity instruction inside the prompt, and a different-provider
warning handled by the runner."""

import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tutor.eval.rubric import Criterion
from tutor.llm.interface import ChatMessage, LLMProvider

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "judge_rubric.md"


logger = logging.getLogger(__name__)


class CriterionScore(BaseModel):
    criterion: str
    # None = the judge itself failed to produce a parseable verdict twice
    # (instrument failure). Excluded from criteria_means — G3/W1 principle:
    # an instrument failure must never kill the run or masquerade as a 0.
    score: int | None = Field(default=None, ge=0, le=2)
    evidence: str = ""
    violations: list[str] = Field(default_factory=list)


def render_judge_prompt(
    criterion: Criterion, transcript_text: str, annotations: str
) -> str:
    text = _PROMPT_PATH.read_text(encoding="utf-8")
    values = {
        "criterion_id": criterion.id,
        "criterion_instructions": criterion.instructions,
        "annotations": annotations,
        "transcript": transcript_text,
    }
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def parse_judge_response(criterion_id: str, content: str) -> CriterionScore:
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise ValueError(f"Judge returned no JSON for {criterion_id}: {content[:200]}")
    data: dict[str, Any] = json.loads(match.group(0))
    data.setdefault("criterion", criterion_id)
    return CriterionScore.model_validate(data)


async def judge_criterion(
    llm: LLMProvider,
    criterion: Criterion,
    transcript_text: str,
    annotations: str,
) -> CriterionScore:
    """One criterion, one judge call — retried ONCE on malformed judge
    output; a second failure yields score=None (skipped in means) instead of
    killing the whole run. Observed live 2026-07-21: DeepSeek-judge returned
    truncated JSON for one criterion and the run died with 4/5 personas'
    work lost — the same instrument-failure class PR-W1 refuses to let lose
    a tutoring turn, applied here to the harness itself."""
    prompt = render_judge_prompt(criterion, transcript_text, annotations)
    last_error = ""
    for _ in range(2):
        response = await llm.complete([ChatMessage(role="user", content=prompt)])
        try:
            return parse_judge_response(criterion.id, response.content)
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
    logger.warning(
        "judge returned unparseable output twice for %s; scoring as None "
        "(excluded from means): %s",
        criterion.id,
        last_error[:200],
    )
    return CriterionScore(
        criterion=criterion.id,
        score=None,
        evidence=f"instrument failure: judge output unparseable twice ({last_error[:120]})",
    )
