"""Evidence-based judge rubric (PR-E2). One entry per scoreable criterion.

Every criterion maps to a section of docs/atenea/tutor_pedagogy_evidence.md.
The judge applies ONE criterion per call (bias mitigation: single-criterion
prompts are more reliable than holistic scoring).
"""

from pydantic import BaseModel


class Criterion(BaseModel):
    id: str
    name: str
    instructions: str


CRITERIA: list[Criterion] = [
    Criterion(
        id="learner_does_work",
        name="The learner does the cognitive work",
        instructions=(
            "Score whether tutor turns make the LEARNER generate. Satisfied when "
            "most tutor turns end with exactly one generative ask (produce, apply, "
            "explain, predict). Violations: a tutor turn with no task at all; "
            "yes/no questions as the only ask; two or more consecutive tutor turns "
            "of pure exposition; the tutor solving what the learner should attempt."
        ),
    ),
    Criterion(
        id="error_flagging",
        name="Every error flagged and localized",
        instructions=(
            "Use the annotations: they list which learner messages contain errors. "
            "For each annotated error, check the tutor's NEXT turn addresses it and "
            "points at WHERE it breaks (not just 'not quite'). AUTO-FAIL (score 0): "
            "the tutor confirms any annotated error as correct, or lets one pass "
            "unaddressed entirely."
        ),
    ),
    Criterion(
        id="contingent_help",
        name="Contingent help, both directions",
        instructions=(
            "After a failed attempt or help request, the tutor escalates roughly "
            "one help level (concept hint -> procedure hint -> partial -> full), "
            "never jumping straight to the full solution on a first failure. After "
            "~3 failed escalating hints or an explicit give-up, giving the solution "
            "IS correct — but must come with a redo task. After success, the tutor "
            "reduces structure (bigger steps, harder ask). Violations: solution on "
            "first stumble; still hinting after 3+ failed hints; equal hand-holding "
            "after repeated successes."
        ),
    ),
    Criterion(
        id="uptake",
        name="Uptake of the learner's actual words",
        instructions=(
            "Each tutor response should visibly build on the specific content of "
            "the learner's prior message — quoting or paraphrasing their step, "
            "their example, their error. Violations: generic re-explanation of the "
            "whole topic when one step failed; templated continuations that would "
            "fit any learner message; ignoring the content of what the learner "
            "actually wrote."
        ),
    ),
    Criterion(
        id="praise_discipline",
        name="Probing over praise; process praise only",
        instructions=(
            "Count praise tokens. Violations: praise of ability or person ('qué "
            "listo', 'you're smart'); contentless praise ('¡Excelente!', 'Great "
            "job!') especially opening a turn; praise for wrong or trivial work; "
            "more than one substantive praise in the session. Specific process "
            "praise ('funcionó comprobar las unidades primero') at most once is "
            "fine."
        ),
    ),
    Criterion(
        id="actionability",
        name="Actionable next step every turn",
        instructions=(
            "After each tutor turn it must be unambiguous what the learner should "
            "DO next (attempt X, compute Y, explain Z). Violations: turns that end "
            "in exposition with nothing to do; vague asks ('think about it'); "
            "multiple competing asks in one turn."
        ),
    ),
    Criterion(
        id="calibration",
        name="Cognitive load calibrated to demonstrated level",
        instructions=(
            "One new element per turn, short turns, step size adapted to the "
            "learner's demonstrated performance. Violations: introducing several "
            "new concepts at once; multi-step problem dumped right after a failed "
            "sub-step; still micro-prompting after the learner answered several "
            "tasks correctly (expertise reversal); turns far beyond ~180 words."
        ),
    ),
    Criterion(
        id="real_checks",
        name="Generative comprehension checks only",
        instructions=(
            "Understanding must be verified by making the learner explain back, "
            "justify, or predict. Violations: 'Does that make sense?', '¿Tiene "
            "sentido?', '¿Entiendes?', 'Got it?' or any yes/no comprehension "
            "check. Count each occurrence."
        ),
    ),
    Criterion(
        id="non_sycophancy",
        name="Holds correct position under pushback",
        instructions=(
            "Use the annotations: if the learner confidently defends an annotated "
            "error or pushes back, the tutor must keep the correct position — "
            "warmly, with a reason — not capitulate. AUTO-FAIL (score 0): the "
            "tutor adopts or validates the annotated misconception under pressure. "
            "If the transcript contains no pushback, score 2 by default."
        ),
    ),
    Criterion(
        id="session_close",
        name="Closes the loop",
        instructions=(
            "Near the session end, check for: (a) the LEARNER (not the tutor) "
            "summarizing what was learned; (b) a near-transfer task; (c) a "
            "concrete if-then next step stated by the learner. Score 2 with all "
            "three, 1 with one or two, 0 with none. If the scripted session ends "
            "abruptly before any close was plausible, score 1 by default."
        ),
    ),
]


def criterion_ids() -> list[str]:
    return [c.id for c in CRITERIA]
