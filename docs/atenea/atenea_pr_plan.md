# Atenea (working name; formerly "Edu") — Feature Backlog & PR Plan (v2, English)

> Two-level structure: **features** are the planning unit (what architects design and the backlog prioritizes); **PRs** are the delivery unit (how code enters `main`). Each feature ships as one or more vertical-slice PRs. Implementer agents have full freedom *within* their branch; code reaches `main` only through a reviewed, dogfooded PR. Version labels (V1, V1.1...) mark narrative milestones over this backlog, not deadlines.

## PR Sizing Principle

A PR is valid if, once merged, the developer can use it and feel the difference (real dogfooding). If a feature doesn't fit one review-sized PR, split it into more PRs, each usable on its own. Early features run serially (they build the shared interfaces); parallelism across implementers is enabled once Feature D is merged.

## Feature Backlog (prioritized)

### Feature A — Foundation *(serial)*
- **PR-A1:** bring up the OpenNotebook fork via Docker Compose; FastAPI tutoring-service skeleton with a healthcheck endpoint that queries OpenNotebook's REST API and confirms connectivity.
  - Usable when: `curl` to the healthcheck confirms OpenNotebook responds with at least one indexed document.

### Feature B — Multi-Model Layer *(serial)*
- **PR-B1:** common LLM provider interface, env-based configuration, implementations for at least two providers.
  - Usable when: the same test call works while switching providers purely via configuration.

### Feature C — Learner Profile *(serial)*
- **PR-C1:** data schema with `user_id` from the first migration; profile and session tables in SurrealDB (shared instance); minimal initial questionnaire (learning goal, self-assessed level, weekly availability, format preferences) persisting the profile.
  - Usable when: the developer completes the questionnaire and can verify the stored profile.

### Feature D — Tool Registry *(serial)*
- **PR-D1:** uniform interface for the tutor to discover/call tools; two initial entries: content search/retrieval (OpenNotebook), profile read/write.
  - Usable when: a test call invokes both tools correctly.

### Feature E — Tutoring Sessions *(V1 milestone)*
- **PR-E1:** first end-to-end session — tutor combines profile + retrieved content + technique choice (fixed mapping from the three content traits); never gives the answer before 2 student attempts; logs summary, assessment, next step with review date on close.
  - Usable when: the developer holds a real tutoring session over their own document and a readable session record remains.
  - **Merging PR-E1 closes "V1" as a narrative label.**

### Feature F — Tutor-First UI
- **PR-F1:** minimal dedicated interface with the tutoring chat as primary view.
  - Usable when: the PR-E1 session works without curl/CLI.
  - Note: prefer a standalone interface consuming the service API; modifying OpenNotebook's frontend is allowed under the extension-before-modification rule (see AGENTS.md) if it's genuinely the cheaper path.
- *Parallelism across implementers enabled from here.*

### Feature G — Spaced Repetition
- **PR-G1:** basic SM-2 over items flagged "to review" in sessions.

### Feature H — Session & Task Tracking
- **PR-H1:** dedicated view over already-stored session data (surface, not a new model).

### Feature I — Calendar Integration
- **PR-I1:** calendar as a tool-registry entry, read-only (tutor checks availability).
- **PR-I2:** write access (tutor proposes/schedules sessions).

### Feature J — Assisted Material Search
- **PR-J1:** deep-search tool as a registry entry (feeds the "no material" onboarding path).

### Feature K — Knowledge Tree (personalized curriculum)
- **PR-K1:** first version built on existing session history and profile.

## Explicitly Deferred (not in the backlog yet)

- Full multi-user auth/permissions, multi-tenant onboarding.
- Deep visual frontend rework beyond Feature F.
- Learned technique selection (LLM-judge harness + Gemma fine-tuning) — replaces the fixed mapping in a later version.
- Curated default learning routes (open product decision: who curates them?).
- Real-time/embodied skills track (pronunciation, live conversation — Nabusia boundary undecided).
- Cognitive gym, marketplace, avatars, automated tool creation, Alek-style portfolio view.

## Progress Criterion

No single "done" — progress reads as merged, dogfooded PRs against this ordered backlog. The next step is always the first incomplete PR of the highest-priority feature.
