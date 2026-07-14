# Agent memory management — SOTA review (2025–26) and what it means for Atenea

> Research note (2026-07-14). Seeds Feature G's next slice (PR-G2, consolidated
> learner-memory). Not an implementation contract — a map of the field plus a
> concrete recommendation for review.

## 1. The mental model everyone converged on

Agent memory is described with a small, stable vocabulary:

- **Tiers.** *Short-term* = tokens inside the context window (sensory + working
  memory). *Long-term* = anything persisted across sessions. Hierarchical
  designs add a middle tier (STM / MTM / long-term "personal" memory, e.g.
  MemoryOS).
- **Operations.** Store → **consolidate** (STM→LTM) → **update** → **forget /
  evict** → **retrieve**. The recent survey line ("Rethinking Memory in LLM
  Agents"; "Memory in the Age of AI Agents") organizes the whole field around
  these five.
- **The OS analogy.** MemGPT/Letta framed context like virtual memory: the
  context window is RAM, recall memory is disk cache, archival store is cold
  storage; a memory manager pages entries in/out with an eviction policy driven
  by recency + LLM-judged importance. This analogy is now the default framing.

## 2. The two dominant product philosophies

- **Managed-fact memory** (Mem0, Zep). A "memory layer / smart cache" bolted onto
  your existing agent loop: the platform extracts facts, ranks them, and returns
  context. Fast to adopt; the platform decides what matters. Zep backs this with
  a temporal knowledge graph. Best for "remember the user across sessions."
- **Agent-controlled tiered memory** (Letta/MemGPT). A full runtime where the
  agent itself calls tools (`core_memory_append`, `archival_memory_insert/
  search`) to decide what to promote, archive, or retrieve. More coherent for
  long-horizon work; you adopt its orchestration.

Other notable mechanisms: **A-MEM** (atomic, semantically-linked notes with
*supersede detection* for staleness), **MemoryBank** (Ebbinghaus forgetting-curve
scoring), **SAGE** (a *novelty gate* — only write genuinely new information),
**Generative Agents** (Park 2023 — a memory stream retrieved by
recency+importance+relevance, plus periodic *reflection* that synthesizes
higher-level memories).

## 3. Consolidation & retrieval — how the good systems actually work

- **Consolidation** is usually **summarization** into unstructured notes
  (MemoryBank, ChatGPT-style rolling summaries), increasingly with **local
  merge** (a new memory retrieves its top-K similar notes; an LLM decides whether
  to merge/supersede) — this keeps memory compact instead of ever-growing.
- **Indexing / retrieval** splits into **graph-based**, **timeline/temporal**,
  and **signal-enhanced** paradigms. The classic retrieval score is a weighted
  sum of **recency + relevance + importance** (Generative Agents, MemoryBank).
- **Reflection** (periodically distilling raw episodes into higher-level beliefs)
  is what turns a log into a *model*.

## 4. Forgetting / eviction — the hard, half-solved part

- Eviction policies are typically **scored** (recency + relevance + importance,
  Ebbinghaus-style decay) rather than FIFO.
- **Selective forgetting is where systems still fail conspicuously.** The
  orchestration tradeoff: page the wrong things in and you waste context tokens;
  archive too aggressively and you get "memory blindness." Getting this right is
  an open research frontier, not a solved recipe.
- Eviction ≠ deletion in the good designs: an item leaves the *active working
  set* but a consolidated trace is retained.

## 5. Tutoring-specific frontier (most relevant to Atenea)

This is where the general field meets pedagogy, and it's very active in 2025:

- **LOOM** — a *dynamic learner memory graph*: infers evolving learner needs from
  conversations and assembles personalized materials toward long-term mastery.
  (The clearest instance of "consolidated learner model as memory.")
- **"Teaching According to Students' Aptitude"** — persona-, memory-, and
  **forgetting-aware** LLM tutoring: explicitly rejects the *static memory*
  assumption (retrieving past records as-is) and models how retention decays.
- **Knowledge tracing (KT)** — the pedagogy field's learner model: Bayesian KT
  (Corbett & Anderson 1994) → deep KT → **LefoKT** (models *relative forgetting*)
  and **MemoryKT** (temporal VAE for knowledge evolution). **TutorLLM** =
  learner model + RAG + KT to pick the next step by *predicted mastery*.

Takeaway: SOTA tutoring memory is a **consolidated, decaying learner model**
(mastery per skill/topic, common errors, retention estimate), retrieved into each
session — not a pile of raw transcripts.

## 6. Where Atenea is, and the gap

What Atenea already has (maps cleanly onto the tiers):

| Tier | SOTA name | Atenea today |
|------|-----------|--------------|
| STM / working | context window | the live session transcript |
| MTM / episodic | session logs | `session` records (summary, assessment, next_step, review_date) |
| LTM / semantic | consolidated model | **missing** — no consolidated learner model |

PR-G1 added a crude working-set (the due queue via `review_date`) with
**count-based** graduation-eviction. That is the right *shape* but the weakest
version of every mechanism above: no consolidation, no reflection, and a
forgetting rule that ignores actual retention.

## 7. Recommendation for PR-G2 (consolidated learner-memory)

A concrete, Atenea-shaped, additive next slice — **to be contracted and reviewed,
not built unsupervised**, because consolidation quality and selective forgetting
are exactly the unsolved parts:

1. **Add the LTM tier.** A new tutor-DB table `learner_memory` keyed by
   user_id + topic/skill: a compact evolving note (mastery estimate, recurring
   errors, last-seen, retention/strength) — the durable **"how far you've come"**
   summary Juan asked for. This is what survives review-eviction.
2. **Consolidate on close (reflection).** At session close, merge the episode
   into the topic's `learner_memory` note (summarize + local-merge / supersede,
   A-MEM-style) rather than leaving knowledge scattered across session rows.
3. **Make forgetting retention-aware, not count-based.** Replace G1's fixed
   `GRADUATION_REVIEWS` with a decay/strength model (SM-2 ease-factor or a
   LefoKT-style relative-forgetting estimate); eviction = strength high & stable.
4. **Retrieve the learner-model slice at session open** (recency + relevance +
   importance), injecting the topic's consolidated note — extends G1's injection
   from raw episodes to the distilled model.
5. **Surface it.** A "tu progreso" view over `learner_memory` = the student's
   map of what they've mastered / what's decaying (pairs with H1).

Fit: entirely additive in the tutor's `atenea` DB, consumed through the existing
engine — **no core changes**, OpenNotebook still used only for content. Philosophy
stays "agent-controlled tiered memory" (Letta-like), which suits a tutor that must
own its pedagogy, over a managed-fact layer (Mem0-like) that would hide the model.

## Sources

- Rethinking Memory in LLM-based Agents: Representations, Operations, Emerging Topics — https://arxiv.org/pdf/2505.00675
- Memory in the Age of AI Agents (survey) — https://arxiv.org/pdf/2512.13564 · list: https://github.com/Shichun-Liu/Agent-Memory-Paper-List
- Memory for Autonomous LLM Agents: Mechanisms, Evaluation, Emerging Frontiers — https://arxiv.org/html/2603.07670v1
- Mem0 vs Letta (MemGPT) comparisons — https://vectorize.io/articles/mem0-vs-letta · https://tokenmix.ai/blog/ai-agent-memory-mem0-vs-letta-vs-memgpt-2026
- Agent memory frameworks 2026 (Mem0/Zep/Letta) — https://atlan.com/know/best-ai-agent-memory-frameworks-2026/
- SAGE: A Novelty Gate for Efficient Memory Evolution — https://arxiv.org/pdf/2605.30711
- Hierarchical Memory for Long-Term Reasoning in LLM Agents — https://arxiv.org/pdf/2507.22925
- LOOM: Personalized Learning via a Dynamic Learner Memory Graph — https://arxiv.org/abs/2511.21037
- Teaching According to Students' Aptitude: Persona-, Memory-, Forgetting-Aware LLM tutoring — https://arxiv.org/html/2511.15163v1
- DKT2 (knowledge tracing at scale) — https://arxiv.org/pdf/2501.14256
