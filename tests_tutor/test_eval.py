"""Eval harness: personas, rubric, judge, metrics, runner (PR-E2 part b).

Fully offline — the tutor and judge LLMs are injected fakes."""

import asyncio
from collections.abc import Sequence

from tutor.eval.judge import parse_judge_response, render_judge_prompt
from tutor.eval.metrics import transcript_metrics
from tutor.eval.personas import annotations_digest, load_personas
from tutor.eval.rubric import CRITERIA, criterion_ids
from tutor.eval.runner import format_transcript, run_eval
from tutor.llm.interface import ChatMessage, ChatResponse
from tutor.session.models import Turn

CLASSIFY = (
    '{"verifiability": "verifiable", "structure": "hierarchical", '
    '"production": "apply"}'
)
CLOSE = '{"summary": "s", "assessment": "a", "next_step": "n", "review_in_days": 3}'


class ScriptedLLM:
    """Tutor fake: classify, then a marker-bearing reply per learner turn."""

    def __init__(self) -> None:
        self._n = 0

    async def complete(self, messages: Sequence[ChatMessage]) -> ChatResponse:
        self._n += 1
        joined = " ".join(m.content for m in messages)
        if "Classify the following study topic" in joined:
            content = CLASSIFY
        elif "The tutoring session below is ending" in joined:
            content = CLOSE
        else:  # a session turn (system prompt is "You are Atenea...")
            content = f"[[TASK: paso {self._n}]] Haz el paso {self._n}."
        return ChatResponse(content=content, provider="fake-tutor", model="m")


class FixedJudge:
    """Judge fake: always returns a valid per-criterion JSON with score 2."""

    async def complete(self, messages: Sequence[ChatMessage]) -> ChatResponse:
        prompt = messages[0].content
        cid = prompt.split("## Criterion: ")[1].split("\n")[0].strip()
        return ChatResponse(
            content=(
                f'{{"criterion": "{cid}", "score": 2, '
                f'"evidence": "ok", "violations": []}}'
            ),
            provider="fake-judge",
            model="m",
        )


def test_personas_load_with_annotations() -> None:
    personas = load_personas()
    assert len(personas) >= 4
    ids = {p.id for p in personas}
    assert {"novato_se_atasca", "adversarial_pushback"} <= ids
    digest = annotations_digest(personas[0])
    assert "L1" in digest


def test_rubric_has_expected_criteria() -> None:
    ids = criterion_ids()
    assert len(ids) == len(set(ids)) == 10
    assert "error_flagging" in ids and "non_sycophancy" in ids


def test_judge_prompt_renders_all_placeholders() -> None:
    prompt = render_judge_prompt(CRITERIA[0], "T1 tutor: hola", "L1: no error")
    assert "{{" not in prompt
    assert CRITERIA[0].id in prompt
    assert "T1 tutor: hola" in prompt


def test_parse_judge_response_extracts_json() -> None:
    score = parse_judge_response(
        "uptake", 'blah {"score": 1, "evidence": "e", "violations": ["v"]} tail'
    )
    assert score.criterion == "uptake" and score.score == 1
    assert score.violations == ["v"]


def test_metrics_count_praise_and_pseudo_checks() -> None:
    transcript = [
        Turn(role="tutor", content="¡Excelente! ¿Tiene sentido? Haz esto."),
        Turn(role="learner", content="vale"),
    ]
    m = transcript_metrics(transcript)
    assert m["praise_tokens"] >= 1
    assert m["pseudo_checks"] >= 1
    assert m["tutor_turns"] == 1 and m["learner_turns"] == 1


def test_format_transcript_numbers_turns() -> None:
    text = format_transcript(
        [Turn(role="tutor", content="a"), Turn(role="learner", content="b")]
    )
    assert "T1 tutor: a" in text and "L1 learner: b" in text


def test_run_eval_end_to_end_with_fakes() -> None:
    personas = load_personas()[:2]
    report = asyncio.run(run_eval(personas, ScriptedLLM(), FixedJudge(), "t", "j"))
    assert report["overall_mean"] == 2.0
    assert set(report["criteria_means"]) == set(criterion_ids())
    assert len(report["personas"]) == 2
    # markers are stripped from the learner-facing transcript text but the
    # metrics still see the raw stored transcript
    assert report["personas"][0]["metrics"]["tutor_turns"] >= 1
