"""Eval runner (PR-E2): simulate persona sessions, score them, build a report.

W1-eval addendum (2026-07-19): the fifth, grounded persona
(`05_grounded_miscitas.json`) exercises the whole-source-lite grounding path
and, when `verify_turns != "off"`, the PR-W1 verification gate. Two
measurements specific to that persona are reported OUTSIDE `criteria_means`
so the 10-criteria mean stays comparable across every prior (sourceless,
ungated) eval run: a programmatic `invented_citations` count
(`tutor.eval.metrics`) and a judge-scored `citation_check`
(`tutor.eval.rubric.CITATION_CHECK`, deliberately not in `CRITERIA`).
"""

from datetime import datetime, timezone
from typing import Any

from tutor.eval.fakes import InMemorySessionStore, build_fake_registry
from tutor.eval.judge import CriterionScore, judge_criterion
from tutor.eval.metrics import invented_citations, transcript_metrics
from tutor.eval.personas import Persona, annotations_digest
from tutor.eval.rubric import CITATION_CHECK, CRITERIA
from tutor.llm.interface import LLMProvider
from tutor.session.engine import TutorEngine
from tutor.session.grounding import DEFAULT_BUDGET_TOKENS, retrieve_grounding
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


def _aggregate_verification(transcript: list[Turn]) -> dict[str, Any]:
    """W1-eval addendum, measurement (3): per-persona aggregation of the
    verification trace already persisted on gated tutor turns
    (`Turn.verification`, PR-W1) — how many turns were gated, the outcome
    distribution, and the total attempt count across them. Empty/zeroed for
    every sourceless persona and for any run with `verify_turns=off`."""
    outcomes: dict[str, int] = {}
    gated_turns = 0
    total_attempts = 0
    for turn in transcript:
        if turn.role != "tutor" or not turn.verification:
            continue
        gated_turns += 1
        outcome = str(turn.verification.get("outcome") or "unknown")
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        total_attempts += len(turn.verification.get("attempts") or [])
    return {
        "gated_turns": gated_turns,
        "outcomes": outcomes,
        "total_attempts": total_attempts,
    }


async def run_persona_session(
    persona: Persona,
    tutor_llm: LLMProvider,
    *,
    verifier_llm: LLMProvider | None = None,
    verify_turns: str = "off",
    verify_profile: str = "high",
    grounding_budget_tokens: int = DEFAULT_BUDGET_TOKENS,
) -> tuple[list[Turn], dict[str, Any]]:
    """One full session (open → scripted turns → close) with in-memory fakes.

    W1-eval addendum: when `persona.source_id` is set the engine grounds the
    session (`grounding_enabled=True`, whole-source-lite) and gates replies
    per `verify_turns`/`verify_profile`; this is the ONLY lever between a
    baseline (`verify_turns="off"`) and a gated (`"grounded"`/`"high"`) eval
    run. Sourceless personas keep every one of these arguments at its
    pre-addendum default (grounding off, verification off) — byte-identical
    to the pre-addendum runner (lock test)."""
    engine = TutorEngine(
        llm=tutor_llm,
        registry=build_fake_registry(persona),
        store=InMemorySessionStore(),
        user_id="eval",
        grounding_enabled=bool(persona.source_id),
        verifier_llm=verifier_llm,
        verify_turns=verify_turns,
        verify_profile=verify_profile,
        grounding_budget_tokens=grounding_budget_tokens,
    )
    state, _ = await engine.open(persona.topic, source_id=persona.source_id)
    for turn in persona.turns:
        state, _ = await engine.message(state.session_id, turn.text)
    record = await engine.close(state.session_id)
    transcript = [Turn.model_validate(t) for t in record.get("transcript") or []]
    return transcript, record


async def evaluate_persona(
    persona: Persona,
    tutor_llm: LLMProvider,
    judge_llm: LLMProvider,
    *,
    verifier_llm: LLMProvider | None = None,
    verify_turns: str = "off",
    verify_profile: str = "high",
    grounding_budget_tokens: int = DEFAULT_BUDGET_TOKENS,
) -> dict[str, Any]:
    transcript, _record = await run_persona_session(
        persona,
        tutor_llm,
        verifier_llm=verifier_llm,
        verify_turns=verify_turns,
        verify_profile=verify_profile,
        grounding_budget_tokens=grounding_budget_tokens,
    )
    transcript_text = format_transcript(transcript)
    annotations = annotations_digest(persona)
    scores: dict[str, CriterionScore] = {}
    for criterion in CRITERIA:
        scores[criterion.id] = await judge_criterion(
            judge_llm, criterion, transcript_text, annotations
        )

    metrics = transcript_metrics(transcript)
    citation_check: dict[str, Any] | None = None
    grounded_persona = persona.source_id is not None
    if grounded_persona:
        # Re-derive which grounding mode actually applied (whole-source vs
        # scoped) rather than assume — the persona is DESIGNED to fit the
        # default budget, but `grounding_budget_tokens` is caller-supplied
        # and could be set low enough (e.g. in a test) to force the scoped
        # fallback, which uses a different citation format.
        grounding = await retrieve_grounding(
            build_fake_registry(persona),
            topic=persona.topic,
            source_id=persona.source_id,
            enabled=True,
            budget_tokens=grounding_budget_tokens,
        )
        metrics["invented_citations"] = invented_citations(
            transcript,
            grounded=grounding.grounded,
            whole_source=grounding.whole_source,
            source_id=persona.source_id,
        )
        citation_score = await judge_criterion(
            judge_llm, CITATION_CHECK, transcript_text, persona.source_text
        )
        citation_check = citation_score.model_dump()
    else:
        metrics["invented_citations"] = invented_citations(transcript, grounded=False)

    return {
        "persona": persona.id,
        "metrics": metrics,
        "scores": {cid: s.model_dump() for cid, s in scores.items()},
        # W1-eval addendum: both keys below are additive and intentionally
        # excluded from `criteria_means` (see module docstring).
        "citation_check": citation_check,
        "verification": _aggregate_verification(transcript),
        "transcript": [t.model_dump() for t in transcript],
    }


async def run_eval(
    personas: list[Persona],
    tutor_llm: LLMProvider,
    judge_llm: LLMProvider,
    tutor_desc: str = "",
    judge_desc: str = "",
    *,
    verifier_llm: LLMProvider | None = None,
    verify_turns: str = "off",
    verify_profile: str = "high",
    grounding_budget_tokens: int = DEFAULT_BUDGET_TOKENS,
) -> dict[str, Any]:
    results = [
        await evaluate_persona(
            p,
            tutor_llm,
            judge_llm,
            verifier_llm=verifier_llm,
            verify_turns=verify_turns,
            verify_profile=verify_profile,
            grounding_budget_tokens=grounding_budget_tokens,
        )
        for p in personas
    ]
    means: dict[str, float] = {}
    for criterion in CRITERIA:
        values = [
            r["scores"][criterion.id]["score"]
            for r in results
            if r["scores"][criterion.id]["score"] is not None  # skip judge failures
        ]
        means[criterion.id] = round(sum(values) / len(values), 2) if values else 0.0
    return {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "tutor": tutor_desc,
        "judge": judge_desc,
        # W1-eval addendum: the before/after lever, carried into the report
        # so `eval_runs/<ts>.json` and the `eval-reports` branch history are
        # self-describing (which config produced this run).
        "verify_turns": verify_turns,
        "verify_profile": verify_profile,
        "criteria_means": means,
        "overall_mean": (round(sum(means.values()) / len(means), 2) if means else 0.0),
        "personas": results,
    }
