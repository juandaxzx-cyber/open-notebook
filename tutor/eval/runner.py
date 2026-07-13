"""Eval runner (PR-E2): simulate persona sessions, score them, build a report."""

from datetime import datetime, timezone
from typing import Any

from tutor.eval.fakes import InMemorySessionStore, build_fake_registry
from tutor.eval.judge import CriterionScore, judge_criterion
from tutor.eval.metrics import transcript_metrics
from tutor.eval.personas import Persona, annotations_digest
from tutor.eval.rubric import CRITERIA
from tutor.llm.interface import LLMProvider
from tutor.session.engine import TutorEngine
from tutor.session.models import Turn


def format_transcript(transcript: list[Turn]) -> str:
    """Number turns for the judge: T = tutor, L = learner (raw, markers kept)."""
    lines = []
    t_count = l_count = 0
    for turn in transcript:
        if turn.role == "tutor":
            t_count += 1
            lines.append(f"T{t_count} tutor: {turn.content}")
        else:
            l_count += 1
            lines.append(f"L{l_count} learner: {turn.content}")
    return "\n\n".join(lines)


async def run_persona_session(
    persona: Persona, tutor_llm: LLMProvider
) -> tuple[list[Turn], dict[str, Any]]:
    """One full session (open → scripted turns → close) with in-memory fakes."""
    engine = TutorEngine(
        llm=tutor_llm,
        registry=build_fake_registry(persona),
        store=InMemorySessionStore(),
        user_id="eval",
    )
    state, _ = await engine.open(persona.topic)
    for turn in persona.turns:
        state, _ = await engine.message(state.session_id, turn.text)
    record = await engine.close(state.session_id)
    transcript = [Turn.model_validate(t) for t in record.get("transcript") or []]
    return transcript, record


async def evaluate_persona(
    persona: Persona,
    tutor_llm: LLMProvider,
    judge_llm: LLMProvider,
) -> dict[str, Any]:
    transcript, _record = await run_persona_session(persona, tutor_llm)
    transcript_text = format_transcript(transcript)
    annotations = annotations_digest(persona)
    scores: dict[str, CriterionScore] = {}
    for criterion in CRITERIA:
        scores[criterion.id] = await judge_criterion(
            judge_llm, criterion, transcript_text, annotations
        )
    return {
        "persona": persona.id,
        "metrics": transcript_metrics(transcript),
        "scores": {cid: s.model_dump() for cid, s in scores.items()},
        "transcript": [t.model_dump() for t in transcript],
    }


async def run_eval(
    personas: list[Persona],
    tutor_llm: LLMProvider,
    judge_llm: LLMProvider,
    tutor_desc: str = "",
    judge_desc: str = "",
) -> dict[str, Any]:
    results = [await evaluate_persona(p, tutor_llm, judge_llm) for p in personas]
    means: dict[str, float] = {}
    for criterion in CRITERIA:
        values = [r["scores"][criterion.id]["score"] for r in results]
        means[criterion.id] = round(sum(values) / len(values), 2) if values else 0.0
    return {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "tutor": tutor_desc,
        "judge": judge_desc,
        "criteria_means": means,
        "overall_mean": (round(sum(means.values()) / len(means), 2) if means else 0.0),
        "personas": results,
    }
