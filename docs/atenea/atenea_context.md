# Atenea (working name; formerly "Edu") — Context Document (v3, English)

> Purpose: paste this document at the start of any work session (with AI collaborators) to reconstitute full project context without re-explaining. Written for consumption by multiple LLM collaborators (architects and implementers) working on this codebase.

## 1. What Atenea Is

An adaptive learning-tools ecosystem whose core is a **model-agnostic AI tutoring harness with a persistent context layer**. The ecosystem's tools feed synergistically into a per-student context database, which the tutor uses to personalize every session.

- **Core thesis / architectural differentiator:** the abstraction layer is built first; verticals (subjects, domains) are expressed as configurations of the same machinery rather than separate features. The first vertical is built *through* the abstraction to validate it against real instances.
- **Technical foundation:** a fork of **OpenNotebook** (MIT license) — https://github.com/juandaxzx-cyber/open-notebook — which already provides: multimodal ingestion (PDF, video, audio, web, Office), full-text and vector search, context-aware chat with citations, a complete REST API, and multi-provider support (18+ providers, including Vertex AI) via the Esperanto library. Stack: Python/FastAPI + Next.js + SurrealDB, context handling via LangChain.
- **Atenea's added value over OpenNotebook:** (1) a persistent *learner* profile (not just per-project notebooks), (2) a proactive pedagogical loop, (3) tutoring prompts grounded in evidence-based pedagogical standards, (4) the tutor as an agent with access to tools beyond content (tool registry).

## 2. The Loop (canonical formulation)

**Assessment → Contextualization → Tutoring → Contextualization → repeat**

- **Contextualization absorbed planning:** plans and strategies (with their target dates) are created/updated there. The plan is a **dynamic policy** ("what's next given the current state"), not a static document.
- **Assessment is continuous**, woven into every tutoring interaction — not a single gate at the start.
- **Spaced repetition is one technique among several**, not the whole system. Technique selection per session depends on the three content traits plus stored pedagogical research (an early version of that research exists; suspected to be insufficient — needs revisiting). In V1 this selection is a simple hardcoded mapping; migrating to a learned mechanism (via an LLM-judge evaluation harness) is an explicit candidate for a later version, not a V1 requirement.

## 3. Content Model: The Three Traits

All content is characterized along three axes that reconfigure the loop's stages:

1. **Verifiability:** verifiable ↔ interpretive
2. **Structure:** hierarchical ↔ distributed
3. **Production type:** recall ↔ apply ↔ explain/transfer

Current scope: "desk" conceptual knowledge. Embodied and real-time skills (pronunciation, physical technique, performance under pressure) are deferred to a future phase.

## 4. Audience

- **Vision:** broad — students above primary school through pre-doctoral level (both extremes deferred due to their particular needs). Core audience: **self-directed learners (autodidacts)**.
- **Current phase:** the developer building this project is also its first user (the project originated as a remedy to a personal problem; the best possible beta tester). Design should already pave the way for more users (see §7), though multi-user development itself is not an immediate priority.

## 5. Development Process: PR-Based Versioning (replaces the "MVP" framing)

The "MVP as market validation" framing was explicitly dropped: the project has value regardless of external market demand, so there is nothing to "validate" in that sense. The current framing is **continuous iterative development with ongoing dogfooding**, structured as follows:

- **Unit of work = a vertical-slice PR.** Every PR must leave the system in a usable/dogfoodable state — never a half-finished feature. If a feature doesn't fit one review-sized PR, it's split into 2-3 PRs, each usable on its own.
- **The version plan (V1, V1.1, V2...) becomes the prioritized PR backlog order**, not fixed-content phases or deadlines. A version label marks a narrative milestone ("once these N PRs are merged, that's V1"), not a deadline.
- **Why this fits the developer's working pattern:** a merged PR is a binary deliverable with a clear boundary — the same logic as timeboxed work blocks, applied to code structure. It reduces the transition cost of "what's next" because the backlog is already ordered in advance.
- **Parallelism:** only enabled once stable contracts/interfaces exist (data layer, multi-model layer, tool registry). Before that, development is deliberately serial — the risk of parallelizing without interfaces isn't merge conflicts (rare) but conceptual ones: each implementer inventing their own way to access the profile, call the LLM, or talk to OpenNotebook.
- **Operational document:** see "Atenea — PR Plan," which contains the concrete sequence, scope, and "usable" criteria per PR.

## 6. Model Roles in Development (AI team)

- **Architects (system design):** two frontier models in an architect role. Recommended pattern: one proposes, the other audits — not independent parallel design, to avoid divergent visions the developer would then have to arbitrate.
- **Implementers (PR code):** several models in an implementer role. They share no memory with each other or with the architects — the contract between them lives in the repo (this document plus explicit interfaces/schemas per PR), never in undocumented conversation.
- **Coordination:** the developer decides, prioritizes the PR backlog, and assigns an implementer per PR once parallelism is enabled (see §5).

## 7. Architecture Decisions: Paving the Road

Explicit distinction between paving that's cheap-now-expensive-later (do it now) and expensive-now-equally-expensive-later (don't get ahead of it):

**Do now (low cost, high future payoff):**
- **Extension before modification:** prefer the OpenNotebook REST API, new modules, or hooks; core modifications are allowed when extension is clearly worse, but each one is documented (file, reason, upstream-merge risk) in `CORE_CHANGES.md` so divergence stays visible.
- Every data schema includes a `user_id` from the first migration, even though today only the developer exists as a user.
- No global "the user" state anywhere in the service code.
- The tutoring service is **API-first**: any future frontend is just another consumer of that API, not a tightly coupled extension.
- Secrets and configuration (including LLM provider selection) always via environment, never hardcoded.
- The tutor is built from day one as an agent with a **tool registry** (a uniform interface for discovering/calling tools), even though in V1 the registry only has 2 entries (search/retrieve content in OpenNotebook, read/write the profile). Calendar, tracking, etc. get added later as new registry entries, with no surgery to the tutor itself.
- A multi-model layer with a common provider interface (not hardcoding a single provider), since multiple providers will be used from the start.

**Don't get ahead of it (high cost now, doesn't get cheaper by doing it early):**
- Full multi-user authentication/permissions system, multi-tenant onboarding.
- Deep visual frontend rework (even though the current OpenNotebook frontend is perceived as generic/unexciting — it's a full version in its own right, to be tackled once the tutor works and it's clear which interactions deserve dedicated design).

## 8. Mission and Standards

- Values: truth, love of humanity, justice. Goal: democratize genuine **understanding**, not just access to information.
- Evidence-based: science and data analysis as primary sources; user feedback and subjective experience count as signal, weighted by relevance and reliability.
- **Pending:** formalize verifiable *operational* standards (e.g., "every technique used must have grounding in learning-science literature," "the tutor never gives the answer before N attempts from the student"). To be revisited after the initial PR backlog stabilizes.

## 9. Developer Working Profile (for collaborators/AI)

- Solo developer; thinks in systems and product architecture; prefers collaborative refinement and intellectual friction over validation.
- Known pattern: high activation cost, executive-function challenges, fatigue on formatting/writing tasks. **Agreed antidotes:** small units of work with a binary "done" criterion (previously: timeboxed blocks; now also: one PR = one unit), delegating instrumental writing (the developer decides and vetoes; the AI drafts), extra care around "paving the road" since it's an easy vector for scope to grow once there's no external deadline to contain it.
- Current division of labor: the developer = decisions, judgment, backlog prioritization, local testing/dogfooding. Architects = design and cross-auditing. Implementers = code for individual PRs.
