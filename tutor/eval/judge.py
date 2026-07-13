"""LLM judge: applies one rubric criterion per call (PR-E2).

Bias mitigations (docs/atenea/tutor_pedagogy_evidence.md): single-criterion
prompts, reference-anchored annotations from the persona script, explicit
anti-verbosity instruction inside the prompt, and a different-provider
warning handled by the runner."""

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tutor.eval.rubric import Criterion
from tutor.llm.interface import ChatMessage, LLMProvider

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "judge_rubric.md"


class CriterionScore(BaseModel):
    criterion: str
    score: int = Field(ge=0, le=2)
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
    prompt = render_judge_prompt(criterion, transcript_text, annotations)
    response = await llm.complete([ChatMessage(role="user", content=prompt)])
    return parse_judge_response(criterion.id, response.content)
