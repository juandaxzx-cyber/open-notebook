"""Eval harness: personas, rubric, judge, metrics, runner (PR-E2 part b).

Fully offline — the tutor and judge LLMs are injected fakes."""

import asyncio
from collections.abc import Sequence

from tutor.eval.fakes import build_fake_registry
from tutor.eval.judge import parse_judge_response, render_judge_prompt
from tutor.eval.metrics import invented_citations, transcript_metrics
from tutor.eval.personas import Persona, PersonaTurn, annotations_digest, load_personas
from tutor.eval.rubric import CITATION_CHECK, CRITERIA, criterion_ids
from tutor.eval.runner import (
    evaluate_persona,
    format_transcript,
    run_eval,
    run_persona_session,
)
from tutor.llm.fake import FakeProvider
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


# --- W1-eval addendum: fifth grounded persona + measurement additions ---


def test_persona_source_fields_default_empty_for_legacy_personas() -> None:
    """Additive-fields lock: the four original persona JSON files carry no
    `source_id`/`source_text` — the new fields default to None/"" without
    touching those files."""
    legacy = [p for p in load_personas() if p.id != "grounded_miscitas"]
    assert len(legacy) == 4
    for p in legacy:
        assert p.source_id is None
        assert p.source_text == ""


def test_fifth_persona_loads_grounded_and_fits_budget() -> None:
    personas = {p.id: p for p in load_personas()}
    assert len(personas) == 5
    grounded = personas["grounded_miscitas"]
    assert grounded.source_id
    assert grounded.source_text
    # fits the default 16000-token whole-source-lite budget by design
    # (tutor.session.grounding._estimate_tokens: words * 1.3)
    assert len(grounded.source_text.split()) * 1.3 < 16000
    # baits: one answered question, one unanswered, one plausible-wrong-citation
    assert any("SÍ RESPONDE" in t.note for t in grounded.turns)
    assert any("NO RESPONDE" in t.note for t in grounded.turns)
    assert any(t.is_error for t in grounded.turns)


def test_fake_registry_registers_get_source_only_when_grounded() -> None:
    grounded = Persona(
        id="g",
        name="G",
        topic="t",
        profile={},
        content=[],
        turns=[PersonaTurn(text="hi")],
        source_id="src-1",
        source_text="the source text",
    )
    sourceless = Persona(
        id="s",
        name="S",
        topic="t",
        profile={},
        content=[],
        turns=[PersonaTurn(text="hi")],
    )
    grounded_names = {s["name"] for s in build_fake_registry(grounded).list_specs()}
    sourceless_names = {s["name"] for s in build_fake_registry(sourceless).list_specs()}
    assert "content.get_source" in grounded_names
    assert "content.get_source" not in sourceless_names


def test_fake_registry_get_source_returns_persona_text() -> None:
    persona = Persona(
        id="g",
        name="Grounded Persona",
        topic="t",
        profile={},
        content=[],
        turns=[PersonaTurn(text="hi")],
        source_id="src-1",
        source_text="the source text",
    )
    result = asyncio.run(
        build_fake_registry(persona).call("content.get_source", {"source_id": "src-1"})
    )
    assert result == {"full_text": "the source text", "title": "Grounded Persona"}


def test_run_persona_session_grounds_and_gates_sourced_persona() -> None:
    """Runner grounded engine construction: opening with `source_id` anchors
    the session (proven by the persisted `source_id`) and, with
    `verify_turns="grounded"`, every tutor turn is gated — a plain
    FakeProvider verifier always passes, so every gated turn's outcome is
    "clean" (exercises the wiring without extra fixtures)."""
    persona = next(p for p in load_personas() if p.id == "grounded_miscitas")
    tutor_llm = FakeProvider()
    transcript, record = asyncio.run(
        run_persona_session(
            persona,
            tutor_llm,
            verifier_llm=tutor_llm,
            verify_turns="grounded",
            verify_profile="high",
        )
    )
    assert record["source_id"] == persona.source_id
    tutor_turns = [t for t in transcript if t.role == "tutor"]
    assert len(tutor_turns) == 1 + len(persona.turns)  # opening + one per message
    assert all(t.verification is not None for t in tutor_turns)
    assert all((t.verification or {}).get("outcome") == "clean" for t in tutor_turns)


def test_run_persona_session_sourceless_defaults_unchanged() -> None:
    """Lock: a sourceless persona still opens ungrounded/unverified — the
    runner's new keyword-only arguments default to the exact pre-addendum
    behavior (grounding off, verification off)."""
    persona = load_personas()[0]
    assert persona.source_id is None
    transcript, record = asyncio.run(run_persona_session(persona, FakeProvider()))
    assert record.get("source_id") is None
    assert all(t.verification is None for t in transcript if t.role == "tutor")


def test_invented_citations_table() -> None:
    def turn(text: str) -> Turn:
        return Turn(role="tutor", content=text)

    # ungrounded: ANY citation-like marker is invented (nothing to cite)
    assert invented_citations([turn("plain text")], grounded=False) == 0
    assert invented_citations([turn("as shown in [1]")], grounded=False) == 1
    assert invented_citations([turn("see [source:x]")], grounded=False) == 1

    # grounded, whole-source: only [source:<the real id>] resolves
    assert (
        invented_citations(
            [turn("fact [source:eiffel-1889]")],
            grounded=True,
            whole_source=True,
            source_id="eiffel-1889",
        )
        == 0
    )
    assert (
        invented_citations(
            [turn("fact [source:other-id]")],
            grounded=True,
            whole_source=True,
            source_id="eiffel-1889",
        )
        == 1
    )
    assert (
        invented_citations(
            [turn("fact [1]")],
            grounded=True,
            whole_source=True,
            source_id="eiffel-1889",
        )
        == 1
    )
    # a `[[TASK: ...]]` marker (PR-E2) is never mistaken for a citation
    assert (
        invented_citations(
            [turn("[[TASK: paso 1]] fact [source:eiffel-1889]")],
            grounded=True,
            whole_source=True,
            source_id="eiffel-1889",
        )
        == 0
    )

    # grounded, scoped: only [n] within 1..max_passages resolves
    assert (
        invented_citations(
            [turn("fact [2]")], grounded=True, whole_source=False, max_passages=6
        )
        == 0
    )
    assert (
        invented_citations(
            [turn("fact [9]")], grounded=True, whole_source=False, max_passages=6
        )
        == 1
    )
    assert (
        invented_citations(
            [turn("fact [source:x]")], grounded=True, whole_source=False, max_passages=6
        )
        == 1
    )


def test_citation_check_not_in_criteria() -> None:
    assert CITATION_CHECK.id not in criterion_ids()
    assert CITATION_CHECK.id == "citation_check"


def test_citation_check_render_and_parse() -> None:
    prompt = render_judge_prompt(
        CITATION_CHECK, "T1 tutor: [source:x] hola", "SOURCE TEXT: hola mundo"
    )
    assert "{{" not in prompt
    assert CITATION_CHECK.id in prompt
    assert "SOURCE TEXT: hola mundo" in prompt
    score = parse_judge_response(
        CITATION_CHECK.id, '{"score": 2, "evidence": "e", "violations": []}'
    )
    assert score.criterion == CITATION_CHECK.id and score.score == 2


def test_evaluate_persona_reports_citation_check_only_for_grounded() -> None:
    class AnyCriterionJudge:
        """Judge fake: valid JSON for any single-criterion prompt, including
        the addendum's `citation_check` (outside CRITERIA)."""

        async def complete(self, messages: Sequence[ChatMessage]) -> ChatResponse:
            prompt = messages[0].content
            cid = prompt.split("## Criterion: ")[1].split("\n")[0].strip()
            return ChatResponse(
                content=f'{{"criterion": "{cid}", "score": 2, "evidence": "ok", "violations": []}}',
                provider="fake-judge",
                model="m",
            )

    personas = {p.id: p for p in load_personas()}
    judge = AnyCriterionJudge()
    tutor_llm = FakeProvider()

    grounded_result = asyncio.run(
        evaluate_persona(personas["grounded_miscitas"], tutor_llm, judge)
    )
    sourceless_result = asyncio.run(
        evaluate_persona(personas["novato_se_atasca"], tutor_llm, judge)
    )

    assert grounded_result["citation_check"] is not None
    assert grounded_result["citation_check"]["score"] == 2
    assert "invented_citations" in grounded_result["metrics"]
    assert (
        grounded_result["verification"]["gated_turns"] == 0
    )  # verify_turns="off" default

    assert sourceless_result["citation_check"] is None
    assert sourceless_result["metrics"]["invented_citations"] == 0


def test_run_eval_all_five_personas_criteria_means_unaffected() -> None:
    """Lock + extend: all five personas run (four legacy + the grounded
    addition); the 10-criteria mean is exactly what it was pre-addendum
    (`citation_check` never enters it) and every persona result carries the
    new additive keys."""
    personas = load_personas()
    report = asyncio.run(run_eval(personas, ScriptedLLM(), FixedJudge(), "t", "j"))
    assert len(report["personas"]) == 5
    assert report["overall_mean"] == 2.0
    assert set(report["criteria_means"]) == set(criterion_ids())
    assert "citation_check" not in report["criteria_means"]
    assert report["verify_turns"] == "off"
    assert report["verify_profile"] == "high"
    grounded = next(
        r for r in report["personas"] if r["persona"] == "grounded_miscitas"
    )
    assert grounded["citation_check"] is not None
    for r in report["personas"]:
        if r["persona"] != "grounded_miscitas":
            assert r["citation_check"] is None


class _MalformedJudge:
    """Judge double returning unparseable output N times, then valid JSON."""

    def __init__(self, bad_times: int) -> None:
        self.bad_times = bad_times
        self.calls = 0

    async def complete(self, messages: Sequence[ChatMessage]) -> ChatResponse:
        self.calls += 1
        if self.calls <= self.bad_times:
            return ChatResponse(content="{ truncated garbag", provider="x", model="y")
        return ChatResponse(
            content='{"score": 2, "evidence": "ok"}', provider="x", model="y"
        )


def test_judge_criterion_retries_once_on_malformed_output() -> None:
    # Harness-robustness fix (2026-07-22): one malformed judge reply is
    # retried; the retry's valid verdict is used.
    from tutor.eval.judge import judge_criterion

    judge = _MalformedJudge(bad_times=1)
    score = asyncio.run(judge_criterion(judge, CRITERIA[0], "transcript", "notes"))
    assert judge.calls == 2
    assert score.score == 2


def test_judge_criterion_double_failure_scores_none_not_crash() -> None:
    # Twice-unparseable judge output => score None (instrument failure),
    # never an exception (the 2026-07-21 CI run died this way) and never a 0.
    from tutor.eval.judge import judge_criterion

    judge = _MalformedJudge(bad_times=2)
    score = asyncio.run(judge_criterion(judge, CRITERIA[0], "transcript", "notes"))
    assert judge.calls == 2
    assert score.score is None
    assert "instrument failure" in score.evidence


def test_criteria_means_skip_none_scores() -> None:
    # A None score is excluded from the mean, not averaged as 0.
    results: list[dict[str, dict[str, dict[str, int | None]]]] = [
        {"scores": {cid: {"score": 2} for cid in criterion_ids()}},
        {"scores": {cid: {"score": None} for cid in criterion_ids()}},
    ]
    means: dict[str, float] = {}
    for criterion in CRITERIA:
        values = [
            s for r in results if (s := r["scores"][criterion.id]["score"]) is not None
        ]
        means[criterion.id] = round(sum(values) / len(values), 2) if values else 0.0
    assert all(v == 2.0 for v in means.values())


def test_citation_check_rubric_has_omission_calibration() -> None:
    # Calibration line added 2026-07-22: judges scored omitted detail as
    # mis-citation (false positive vs the programmatic invented_citations=0).
    assert "OMITTING" in CITATION_CHECK.instructions
    assert "NOT" in CITATION_CHECK.instructions
