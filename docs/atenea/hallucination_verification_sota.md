# Hallucination verification — SOTA review (2025–26) and what it means for Feature W

> Research note (2026-07-19). Seeds Feature W (LLM output verification layer,
> registered 2026-07-18 by developer decision: verify-before-persist/send,
> verifier stronger than generator, verifier-as-generator on failure). Not an
> implementation contract — a map of the field plus a concrete W1
> recommendation for review. Companion to `agent_memory_sota.md` (PR-G2 shipped
> W's first fenced instance: consolidation verification).

## 1. Why models hallucinate — the 2025 consensus

OpenAI's "Why Language Models Hallucinate" (Kalai, Nachum, Vempala, Zhang,
2025) reframed the field: hallucination is not a bug to patch but a
**statistical consequence of training + evaluation rewarding guessing over
acknowledged uncertainty** — models are graded like exam-takers where a lucky
guess beats an honest "I don't know". Nature (2026) generalized the point:
accuracy-incentivized evals *teach* models to guess. Two implications for any
verification layer:

- Verification must be paired with **permission to abstain / hedge** — a
  verifier that only rejects, attached to a generator that must always answer,
  reproduces the guessing incentive one level up.
- Uncertainty is signal: methods that measure it directly (semantic entropy —
  Farquhar et al., Nature 2024) detect confabulations without any external
  ground truth, at the cost of extra sampling.

## 2. Detection — four families

1. **Sampling/consistency (no ground truth needed):** SelfCheckGPT,
   semantic-entropy variants, FactSelfCheck (fact-level, black-box). Sample
   the model k times; claims that vary are suspect. Robust but k× cost.
2. **Claim decomposition + entailment against evidence:** the dominant
   production family. Decompose output into atomic claims (decontextualization
   matters — DnDScore), then check each against evidence with an LLM/NLI
   judge (CLATTER's comprehensive entailment; RAGAS *faithfulness* and the
   RAG-specific detectors — LettuceDetect, ReDeEP, Trulens groundedness).
   This is exactly the shape of G2's `verify_memory.md`.
3. **Trained verifiers/inspectors:** VerifierQ (Q-learning verifiers), SVIP
   (learned inspector). Stronger but need training data — later-version
   territory for Atenea (same status as learned technique selection).
4. **Tool receipts for agents:** verify tool-derived statements against the
   tool's actual output rather than re-asking an LLM ("Tool Receipts, Not
   Zero-Knowledge Proofs", 2026) — cheap and exact where it applies. Atenea
   analog: claims about the learner's history are checkable against the
   store (G2 already does this for consolidation).

## 3. Correction — generate → verify → revise, and cascades

- **Chain-of-Verification (CoVe, ACL 2024):** draft → generate targeted
  verification questions → answer them independently → synthesize a revised
  response. The canonical single-model loop.
- **Cascades (2026 production practice):** answer with the cheap model,
  escalate on failed confidence/verification checks. Good for cost, **bad for
  latency** (a failed check pays both tiers); Sherlock-style selective/
  speculative verification overlaps the check with downstream work to hide
  that latency.
- **Verifier dynamics (arXiv 2509.17995):** with a fixed competent verifier, a
  *weaker generator approaches the post-verification quality of a stronger
  one*. This is the empirical backbone of the developer's chosen pattern
  (cheap generator + stronger verifier + verifier-takes-over-on-failure): the
  expensive model's tokens are spent only where they provably matter.
- **Education-specific framing (2026):** the converged recipe for tutoring
  products is *ground in a vetted corpus + enforce citations + runtime judge
  scoring faithfulness + gate the response on the judge* — fabricated
  references are singled out as the worst failure mode because students cite
  them downstream.

## 4. Where Atenea stands

| Ingredient | SOTA name | Atenea today |
|---|---|---|
| Trusted grounding | vetted corpus + citations | M1/M2: source-scoped RAG, passages injected with [n] markers, prompt orders cite-from-source |
| Claim-check gate | faithfulness judge | **only for memory writes** (G2: episode+prior-note evidence, verifier-as-generator retry, skip-on-double-fail) |
| Measurement | runtime judge / evals | E2 harness (10 criteria incl. error-flagging, real-checks, calibration) now running in CI (DX3, `eval-reports`) |
| Per-turn verification of what the learner is told | response gating | **missing — this is W1** |
| Abstention policy | calibrated hedging | implicit only (prompt asks honesty; nothing enforces it) |

## 5. Recommendation for W1 (to be contracted, not built unsupervised)

**Verify the tutor's replies to the learner — grounded sessions first.**

1. **Scope by ground truth available.** Grounded sessions have real evidence
   (the injected passages): claim-check each tutor reply against them,
   RAGAS-faithfulness-shaped — one verifier call per turn, checking (a) factual
   claims are supported by the passages or clearly marked as outside them,
   (b) citations [n] actually match what passage n says (mis-citation = the
   education field's worst failure). Ungrounded sessions have no evidence:
   don't pretend to verify — enforce the **abstention side** instead (prompt
   policy + verifier checks only for overclaiming/fabricated references,
   detectable without a corpus).
2. **Escalation per the developer's pattern (G2 precedent):** fail ⇒ verifier
   regenerates the turn with violations as constraints ⇒ re-verify ⇒ still
   fail ⇒ **send with explicit uncertainty flags** rather than block. This is
   the one place W1 must differ from G2: skipping a memory write was safe;
   stalling a live tutoring turn is worse than hedging one. The learner sees
   an honest "no estoy seguro de esto" instead of silence.
3. **Cost/latency controls (env, all reusing G2's `TUTOR_VERIFIER_*`):**
   `TUTOR_VERIFY_TURNS = off | grounded | all` (default `grounded`);
   verify only claim-bearing replies (skip pure questions/task-setting turns —
   cheap heuristic first, no classifier); the cascade's latency cost is real
   (§3) — whether the gate is synchronous (block until verified) or
   asynchronous (send, then correct next turn if the check fails) is an
   **open product decision for the developer**: latency tolerance is his call.
4. **Merge gate = eval evidence.** W1 is the first PR whose contract should
   require a DX3 before/after: error-flagging, real-checks, calibration and
   non-sycophancy scores must not regress, and the dogfoodable claim is
   measurable ("mis-citations per session drop to ~0 on the persona suite").

Fit: additive, tutor-side only (`tutor/session/verification.py` seam, same
one-seam pattern as grounding/memory/scheduling); no core changes; fake
provider gets deterministic verdicts so smoke stays zero-key.

## Sources

- Why Language Models Hallucinate (Kalai, Nachum, Vempala, Zhang, OpenAI 2025) — https://arxiv.org/abs/2509.04664 · https://openai.com/index/why-language-models-hallucinate/
- Evaluating LLMs for accuracy incentivizes hallucinations — https://www.nature.com/articles/s41586-026-10549-w
- Chain-of-Verification (ACL 2024 Findings) — https://arxiv.org/abs/2309.11495
- Detecting hallucinations using semantic entropy (Farquhar et al., Nature 2024) — https://www.nature.com/articles/s41586-024-07421-0
- FactSelfCheck (fact-level black-box detection) — https://arxiv.org/pdf/2503.17229
- DnDScore (decontextualization + decomposition) — https://arxiv.org/pdf/2412.13175
- CLATTER (entailment reasoning for hallucination detection) — https://arxiv.org/pdf/2506.05243
- Fact-checking & factuality evaluation review (Springer AI Review 2025) — https://link.springer.com/article/10.1007/s10462-025-11454-w
- Variation in Verification (verifier/generator dynamics) — https://arxiv.org/abs/2509.17995
- Sherlock (selective/speculative verification in agentic workflows) — https://arxiv.org/pdf/2511.00330
- Cluster, Route, Escalate (cost-aware cascades) — https://arxiv.org/html/2606.27457
- Tool Receipts, Not Zero-Knowledge Proofs (agent hallucination detection) — https://arxiv.org/pdf/2603.10060
- RAGAS (faithfulness family) — https://arxiv.org/abs/2309.15217
- AI hallucination from students' perspective (2026) — https://arxiv.org/html/2602.17671v1
- Hallucination guides, 2026 production framing — https://www.lakera.ai/blog/guide-to-hallucinations-in-large-language-models · https://futureagi.com/blog/understanding-llm-hallucination-2025/
