# Atenea (working name; formerly "Edu") — Feature Backlog & PR Plan (v2, English)

> Two-level structure: **features** are the planning unit (what architects design and the backlog prioritizes); **PRs** are the delivery unit (how code enters `main`). Each feature ships as one or more vertical-slice PRs. Implementer agents have full freedom *within* their branch; code reaches `main` only through a reviewed, dogfooded PR. Version labels (V1, V1.1...) mark narrative milestones over this backlog, not deadlines.

## PR Sizing Principle

A PR is valid if, once merged, the developer can use it and feel the difference (real dogfooding). If a feature doesn't fit one review-sized PR, split it into more PRs, each usable on its own. Early features run serially (they build the shared interfaces); parallelism across implementers is enabled once Feature D is merged.

## Feature Backlog (prioritized)

### Feature A — Foundation *(serial)* ✅ merged 2026-07-12
- **PR-A1:** bring up the OpenNotebook fork via Docker Compose; FastAPI tutoring-service skeleton with a healthcheck endpoint that queries OpenNotebook's REST API and confirms connectivity.
  - Usable when: `curl` to the healthcheck confirms OpenNotebook responds with at least one indexed document.

### Feature B — Multi-Model Layer *(serial)* ✅ merged 2026-07-12
- **PR-B1:** common LLM provider interface, env-based configuration, implementations for at least two providers.
  - Usable when: the same test call works while switching providers purely via configuration.

### Feature C — Learner Profile *(serial)* ✅ merged 2026-07-12
- **PR-C1:** data schema with `user_id` from the first migration; profile and session tables in SurrealDB (shared instance); minimal initial questionnaire (learning goal, self-assessed level, weekly availability, format preferences) persisting the profile.
  - Usable when: the developer completes the questionnaire and can verify the stored profile.

### Feature D — Tool Registry *(serial)* ✅ merged 2026-07-12
- **PR-D1:** uniform interface for the tutor to discover/call tools; two initial entries: content search/retrieval (OpenNotebook), profile read/write.
  - Usable when: a test call invokes both tools correctly.

### Feature E — Tutoring Sessions *(V1 milestone)* ✅ merged 2026-07-12
- **PR-E1:** first end-to-end session — tutor combines profile + retrieved content + technique choice (fixed mapping from the three content traits); applies a graduated-help policy (generation first, hint ladder: conceptual → procedural → partial → full solution; replaces the earlier fixed "2 attempts" rule — decision 2026-07-12, see playbook); logs summary, assessment, next step with review date on close.
  - Usable when: the developer holds a real tutoring session over their own document and a readable session record remains.
  - **Merging PR-E1 closes "V1" as a narrative label.**

### Feature DX — One-Command Startup ✅ merged 2026-07-12
- **PR-DX1:** tutor as a docker-compose service; `docker compose up -d` brings up the full stack.
  - Usable when: cold machine → one command → working session in the browser.

### Feature E2 — Session Quality ✅ merged 2026-07-12
- **PR-E2:** per-task attempt/help state (tutor marks task boundaries) + first prompt-evaluation loop (scripted personas + LLM-judge rubric). See playbook §1.6.
  - Usable when: attempts/help shown per task are honest, and a prompt change can be compared against the rubric before shipping.

### Feature F — Tutor-First UI ✅ merged 2026-07-12
- **PR-F1:** minimal dedicated interface with the tutoring chat as primary view.
  - Usable when: the PR-E1 session works without curl/CLI.
  - Note: prefer a standalone interface consuming the service API; modifying OpenNotebook's frontend is allowed under the extension-before-modification rule (see AGENTS.md) if it's genuinely the cheaper path.
- *Parallelism across implementers enabled from here.*

### Feature F2 — Unified Experience ✅ merged 2026-07-14
- Tutor and OpenNotebook currently feel like two separate apps (UIs, UX, ports). F2 = single entry point + visual pass on the tutor UI. Sharpens the already-deferred "deep visual frontend rework".

### Feature R — Session Resilience ✅ merged 2026-07-14
- **PR-R1:** resume abandoned sessions. Server-side state is already persisted per turn (SurrealDB `session` table, `store.save_progress`); what's lost is the client's `session_id` and any way to find open sessions again. Fix: list-open-sessions endpoint + UI resume path (transcript replay, session id in the URL). **Implemented + committed** on `feature/r/session-resume` @ `c8a0fa2` (66 tests green); pending developer dogfood + merge.
  - Usable when: close the tab mid-session, reopen `localhost:5056`, tap "Continuar" and the conversation is back exactly where it stopped — even after restarting the tutor service.

### Feature G — Cross-Session Memory ✅ COMPLETE — G1 merged 2026-07-14; G2 merged 2026-07-18 (@2dbc60d); G3 merged 2026-07-19 (@3b0a6f6: SM-2 + horizon eviction + visible retention decay). Milestone dogfood pending (DOGFOOD.md); nothing memory-consuming contracts before that dogfood.
- **PR-G1:** cross-session review loop — resurface due prior sessions and revisit them, with an inject / update / evict memory lifecycle. **Implemented @ `ad899f0` on `feature/g/review` (2026-07-14, autonomous, pending review):** `GET /reviews/due` + `POST /review`, `review_system.md` (retrieval-first, interleaved), crude reschedule + graduation-evict, UI "Repasar lo pendiente". Additive, no core, 77 tests. SM-2 refinement + a consolidated learner-memory = PR-G2+ (pending an agent-memory SOTA review).

### Feature H — Session & Task Tracking — H1 ✅ merged 2026-07-14
- **PR-H1:** dedicated view over already-stored session data (surface, not a new model). **Contract signed off + implemented @ `7f4c619` on `feature/h/tracking` (2026-07-14, autonomous, pending review):** `SessionSummary` gains `review_date`; UI 'Historial y progreso' groups sessions (Para repasar / Abiertas / Completadas), each opening via the existing `GET /session/{id}`. Read-only, no schema/core changes, 69 tests green.

### Feature I — Calendar Integration
- **PR-I1:** calendar as a tool-registry entry, read-only (tutor checks availability).
- **PR-I2:** write access (tutor proposes/schedules sessions).

### Feature J — Assisted Material Search
- **PR-J1:** deep-search tool as a registry entry (feeds the "no material" onboarding path).

### Feature K — Knowledge Tree (personalized curriculum)
- **PR-K1:** first version built on existing session history and profile.

### Feature DX2 — Fast Test & Dev Loop ✅ merged 2026-07-14
- **PR-DX2:** fake LLM provider + `make smoke` full-journey test + `make dev`/`make restart`. Enables the V1 review policy (playbook §1.8).

### Feature F3 — UI Completeness ✅ merged 2026-07-14
- **PR-F3:** in-UI profile questionnaire, grounding source picker, provider/model visibility.

## Registered, Unordered (2026-07-12 — developer prioritizes; no contracts yet)

Captured so conversation/agent handoffs never lose them; each needs an architect contract + developer sign-off before implementation.

- **Feature M — Material-Grounded Sessions:** today the engine only sees a small search digest of indexed content. M = sessions anchored to explicitly chosen source(s): pick material at session open, tutor cites back into it, tracks coverage (what of the source has been worked), and generates tasks from the text rather than around it. Interacts with J (search) and K (tree). **Contract signed off 2026-07-14 (playbook §1):** sliced into PR-M1 (tutor-side source-scoped retrieval, zero core changes) → PR-M2 (source filter in core `fn::vector_search`, sequenced after the §4 upstream sync) → later M-coverage / M-tasks. Reuses OpenNotebook's existing RAG substrate (`fn::vector_search`, `ContextBuilder`) over REST rather than rebuilding it. **PR-M1 implemented @ `681197a` on `feature/m/grounding` (2026-07-14, autonomous, pending review):** tutor-side source-scoped retrieval behind `TUTOR_GROUNDING_ENABLED`, diff confined to `tutor/`+`tests_tutor/`, 76 tests green. PR-M2 (core `fn::vector_search` filter) still pending the §4 upstream sync.
- **Feature T — Runtime Tool Creation:** promoted from the deferred list ("automated tool creation"). Tutor-proposed tools enter through the registry (hard rule #5) behind developer approval — never self-installed silently.
- **Feature V — Voice:** speech input/output for sessions; provider via env through the same multi-model philosophy as text (no direct SDK calls in business logic).
- **Feature W — LLM Output Verification Layer (registered 2026-07-18, developer decision):** verify-before-persist/send for LLM outputs across the system, targeting hallucination reduction at accepted extra cost. Architecture to be pinned by a SOTA research note (`docs/atenea/hallucination_verification_sota.md` — claim-checking à la CoVe, verifier cascades, interplay with context management) before contracting. Developer-specified pattern: verifier model stronger than the generator; on failed verification the verifier takes over generation for that turn and/or generation repeats before anything reaches the user or the store. PR-G2 ships the first fenced instance (consolidation verification); W generalizes it.

## Explicitly Deferred (not in the backlog yet)

- Full multi-user auth/permissions, multi-tenant onboarding.
- Deep visual frontend rework beyond Feature F.
- Learned technique selection (LLM-judge harness + Gemma fine-tuning) — replaces the fixed mapping in a later version.
- Curated default learning routes (open product decision: who curates them?).
- Real-time/embodied skills track (pronunciation, live conversation — Nabusia boundary undecided).
- Cognitive gym, marketplace, avatars, Alek-style portfolio view. ("Automated tool creation" moved to Feature T above, 2026-07-12.)

## Progress Criterion

No single "done" — progress reads as merged, dogfooded PRs against this ordered backlog. The next step is always the first incomplete PR of the highest-priority feature.

## Status (2026-07-14, end of day)

**Everything delivered is merged to `main`**: V1 (PR-0 + A–F), DX1, E2, F2, R1, H1, G1, M1, upstream sync (@7dfe8aa), DX2, F3, M2 — one merge commit per PR, verified by 107 tutor tests + the 12-step `make smoke` journey + ruff + mypy. V1-era review policy in effect (playbook §1.8): merges gate on checks + smoke; developer dogfoods at milestones. Push to origin verified done 2026-07-18 (@c22483a); PR-G2 merged 2026-07-18 (@2dbc60d, 130 tests + 14-step smoke green) — `main` now 4 commits ahead of origin, push pending. Pending on developer: push, first-push CI result, live-stack validation of migration 23, milestone browser dogfood (now including G2's "Tu progreso" + memory injection). **Next:** PR-G3, M-coverage / M-tasks, T / V / W. Per-PR contracts live in the playbook; this file stays the backlog-level view. New agent conversations start with the playbook's Handoff Protocol (§6).
