# AGENTS.md — Atenea (working name; formerly "Edu")

> Operational instructions for AI agents working on this codebase. Read together with `atenea_context.md` (project context) and `atenea_pr_plan.md` (feature backlog & PR plan). If anything here conflicts with an undocumented conversation, this file wins until the developer updates it.

## Repository

- This repo is a fork of OpenNotebook (MIT): https://github.com/juandaxzx-cyber/open-notebook (keeping the name for now — rename is an open decision, developer's call; keeping it makes the fork relationship and upstream sync obvious)
- The tutoring service lives in this same repo as a distinct module/service: **`tutor/`** (sibling of `api/` and `open_notebook/` at the repo root)
- Run locally: `docker compose up` (OpenNotebook stack) + `uv run python -m tutor` for the tutoring service (serves FastAPI on `TUTOR_PORT`, default 5056; contract details in `atenea_dev_playbook.md`)
- Python version: **3.12** (see `.python-version`; managed with `uv`) · Env template: keep `.env.example` current — variable names only, never values. Developer provisions API keys on demand; agents must never hardcode or request actual secrets in code or logs.
- Line endings: **LF everywhere**. The repo is configured with `core.autocrlf=input`; never commit CRLF. If a diff shows hundreds of whitespace-only changes, stop and fix your editor/git config instead of committing.

## Agent Hierarchy & Permissions

- **Architect agents** (frontier models, e.g. Fable 5, GPT 5.6 Terra): may design and revise architecture, restructure the backlog *proposal*, define PR contracts, and audit each other. Pattern: one proposes, the other audits — no independent parallel designs.
- **Implementer agents** (e.g. Grok 4.5, Sonnet 5, GPT 5.6 Luna): implement one PR at a time against a contract fixed by architects in writing. Full freedom *within* the branch (commits, structure, exploration); no authority to change contracts, schemas, or backlog order.
- **The developer** is the final authority: prioritizes the backlog, reviews, merges, and dogfoods every PR. Nothing enters `main` without their review.
- **Open product decisions are reserved to the developer.** Currently open (do not resolve unilaterally): who curates default learning routes; the Atenea/Nabusia boundary for language learning; which version gets the portfolio view. If blocked by one of these, flag it in the PR description instead of deciding.

## Hard Rules (apply to all agents)

1. **Extension before modification.** Prefer the OpenNotebook REST API, new modules, or hooks. Modifying OpenNotebook core is *allowed* when extension is clearly worse — but every core modification must be documented in `CORE_CHANGES.md` (file touched, reason, upstream-merge risk) so divergence stays visible instead of accumulating silently.
2. **API-first.** The tutoring service exposes a clean API; any frontend is just another consumer.
3. **`user_id` in every schema** from the first migration; no global "the user" state.
4. **All configuration via environment**, including LLM provider selection. Provider access only through the common multi-model interface (Feature B) — never direct SDK calls scattered in business logic.
5. **Tools only via the tool registry.** New tutor capabilities are new registry entries, not surgery on the tutor.
6. **One PR = one dogfoodable vertical slice.** If it can't be used after merge, the slice is cut wrong.

## Code Conventions

- **Tests are mandatory** for non-trivial logic: unit tests for pure rules (SM-2, trait→technique mapping), integration tests for the tool registry and API endpoints. A PR does not merge with failing tests.
- Type hints throughout; Pydantic models at all boundaries (API, DB, LLM I/O).
- Formatting/linting: `ruff` (format + lint) — no style debates in review.
- Branches: `feature/<feature-letter>/<slice>` (e.g. `feature/c/questionnaire`).
- Commits: conventional style (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`).
- PR descriptions must: link the feature in `atenea_pr_plan.md`, state the contract implemented, and include a **"How to dogfood this"** section (exact steps for the developer).
- Language: code, comments, docs, and PRs in **English**.

## Orientation for a New Agent

1. Read `atenea_context.md` (what/why), then `atenea_pr_plan.md` (what's next), then this file (how), then `atenea_dev_playbook.md` (current PR contract and operational checklist