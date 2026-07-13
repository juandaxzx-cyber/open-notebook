# Evidence Base for Atenea's Pedagogy (PR-E2)

Canonical basis for the session master prompt (`tutor/prompts/session_system.md`)
and the LLM-judge rubric (`tutor/eval/rubric.py`). Compiled 2026-07-12 from two
research passes over the tutoring-effectiveness and tutor-evaluation literature.
When prompt and rubric disagree with intuition, this document wins.

## Framing result

Human tutoring is d ≈ 0.79 vs. no tutoring, and step-based ITSs already reach
d ≈ 0.76 (VanLehn 2011, reassessing Bloom's "2 sigma"). The advantage does NOT
come from deep learner diagnosis — tutors are demonstrably poor at modeling
learner mental models (Chi, Siler & Jeong 2004) — but from **interaction
granularity**: keeping the learner actively producing at step level, with
feedback and scaffolding at each step. All of this is observable in a chat
transcript, hence judgeable.

## Within-session behaviors (evidence → rubric criterion)

1. **Learner constructs, tutor scaffolds** (Chi et al. 2001: tutors barred
   from explaining produced equal learning — gains come from what the learner
   generates; ICAP hierarchy, Chi & Wylie 2014 — strong). → criterion
   `learner_does_work`.
2. **Flag and localize every error; never confirm a wrong answer** (Hattie &
   Timperley 2007; Shute 2008; Graesser 1995: unflagged errors are a mediocre-
   tutor signature; MRBench/BEA 2025: mistake identification is also the most
   reliably LLM-judgeable criterion — strong). → `error_flagging`.
3. **Contingent help, both directions** (Wood, Bruner & Ross 1976; Wood & Wood
   1999: +1 help level after failure, fade after success; Koedinger & Aleven
   2007 "assistance dilemma": pure withholding and pure telling both fail;
   VanLehn 2003: telling works precisely at impasses — strong). Telling after
   ~3 failed escalating hints is CORRECT behavior, not a violation.
   → `contingent_help`.
4. **Uptake: respond to the learner's actual words** (Demszky et al. 2021;
   M-Powering Teachers RCT 2024: the only criterion with an RCT-validated
   automated measure linked to outcomes — strong). Targeted remediation of the
   specific flawed step beats broadcast re-explanation (Graesser EMT).
   → `uptake`.
5. **Probing over praise; process praise only, sparingly** (Tutor CoPilot RCT
   2024, n≈1,800: shifting tutors from generic praise to probing questions
   raised mastery +4pp; Mueller & Dweck 1998: person-praise harms persistence
   — strong). → `praise_discipline`.
6. **Actionable next step every turn** (MRBench "actionability"; BEA 2025).
   → `actionability`.
7. **Cognitive load calibrated to demonstrated level** (Sweller/Kalyuga
   expertise reversal: heavy structure helps novices and HARMS the competent;
   one new element per turn; short feedback beats long — Shute 2008 — strong).
   Micro-prompting a learner who keeps succeeding is a failure. → `calibration`.
8. **Generative comprehension checks** (Bisra et al. 2018 self-explanation
   meta-analysis g=0.55; Graesser 1995: "Does that make sense?" is a
   pseudo-check learners always answer yes to — strong). → `real_checks`.
9. **Non-sycophancy** (2024-25 educational-sycophancy literature; Bridge:
   novice tutors capitulate under confident pushback). → `non_sycophancy`.
10. **Close the loop** (learner-produced recap; near-transfer task; if-then
    next step — implementation intentions meta-analyses, Gollwitzer & Sheeran;
    review date ≈10-20% of the retention interval, Cepeda et al. 2008).
    → `session_close`.

## Failure modes of mediocre tutors (all penalized by the rubric)

Knowledge-telling/lecture default; "do you understand?" pseudo-diagnosis;
non-contingent help (over-helping success, jumping to answers on failure);
letting errors slide; indiscriminate or person-directed praise
(Graesser 1995; Chi 2001/2004; Wood & Wood 1999; Hattie & Timperley 2007;
Mueller & Dweck 1998).

## What does NOT work (guard against plausible-sounding regressions)

- Deep learner-model narration: no leverage (VanLehn 2011; Chi 2004).
- Pure Socratic withholding: backfires at impasses (Koedinger & Aleven 2007).
- Unprompted pre-impasse explanations: little learning (VanLehn 2003);
  instruction-first loses to attempt-first for concepts (Sinha & Kapur 2021,
  g=0.36).
- Person praise and praise density: harms (Mueller & Dweck 1998).
- Long feedback: ignored (Shute 2008).
- One-size guidance: expertise reversal (Kalyuga 2007).

## LLM-judge design (mitigations baked into `tutor/eval/`)

Known biases: verbosity (rewards exposition — anti-correlated with tutoring
quality), self-preference (judge inflates its own model family), sycophancy
toward the learner's frame, and a hard ceiling on judging "guidance quality"
(BEA 2025: best systems reach macro-F1 0.58-0.72 vs. human labels).
Mitigations: one prompt per criterion (never holistic 1-10); judge from a
different provider than the tutor (runner warns otherwise); reference-anchored
judging (personas carry ground-truth error annotations, the judge verifies
instead of guessing); programmatic no-LLM metrics alongside (word ratios, turn
lengths, praise-token counts); one adversarial persona (confident wrong
pushback) to catch capitulation.

## Deferred (backlog, with evidence attached)

- **Session-opening retrieval of PRIOR sessions' material to criterion**
  (successive relearning, Rawson & Dunlosky 2022: > a letter grade vs.
  restudy). Needs cross-session memory injection — Feature G territory.
- **Real spaced review scheduling** (Cepeda 2008 gap ≈ 10-20% of retention
  interval) and **interleaving old problem types** (Rohrer 2020 RCT d=0.83).
  Same dependency.
- **Cadence/habit support** (Lally 2010; NSSA dosage standards): product
  feature, not prompt.

Primary sources are linked in the PR-E2 research transcripts; key citations:
VanLehn 2011 (Ed. Psychologist 46:4); Chi et al. 2001 (Cog. Sci. 25);
Chi & Wylie 2014 (ICAP); Graesser, Person & Magliano 1995; VanLehn et al. 2003
(Cog. & Instruction 21); Wood & Wood 1999 (Computers & Education); Koedinger &
Aleven 2007 (Ed. Psych. Review); Lepper & Woolverton 2002 (INSPIRE); Hattie &
Timperley 2007; Shute 2008; Mueller & Dweck 1998; Bisra et al. 2018; Adesope
et al. 2017; Kalyuga 2007; Sinha & Kapur 2021; Demszky et al. 2021/2024;
Wang et al. 2024 (Bridge); Maurya et al. 2025 (MRBench); BEA 2025 shared task;
Tutor CoPilot 2024; LearnLM 2024/2025; Cepeda et al. 2008; Rawson & Dunlosky
2022; Rohrer et al. 2020; Gollwitzer & Sheeran; Lally et al. 2010.
