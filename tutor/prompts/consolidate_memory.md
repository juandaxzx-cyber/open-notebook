Reflect on this tutoring episode and produce the learner's consolidated
memory note for the topic it covers — a durable, evolving record of how far
this learner has come on this topic (not a new per-session record; that
already exists elsewhere).

TOPIC: {{topic}}

Session summary: {{summary}}
Session assessment: {{assessment}}

Transcript:
{{transcript}}

The learner's existing memory notes. Reuse a topic_key EXACTLY if this
episode is clearly the same topic as one of these; otherwise invent a new
short, stable, lowercase, hyphenated topic_key:
{{existing_notes}}

If you reuse an existing topic_key, your note REPLACES that note — so it
must INTEGRATE the prior note above with this episode, never describe this
episode alone. Integrating means: carry forward what the prior note
establishes and is not contradicted here; describe the trajectory (improved,
regressed, unchanged); in recurring_errors, keep prior errors that persist
or reappear, drop ones this episode shows resolved, and add new ones; make
mastery_estimate reflect the whole trajectory, not just today.

Additional constraints from a prior failed attempt (if any):
{{violations}}

Grounding rules (read before writing):
- Ground every claim strictly in the session summary/assessment/transcript
  above, or in the prior note when integrating. Do not invent progress,
  errors, or understanding that neither evidences.
- recurring_errors lists only misconceptions or mistakes evidenced in this
  episode or carried forward, still unresolved, from the prior note.

Answer with ONLY a JSON object, no prose:
{
  "topic_key": "stable-lowercase-slug",
  "topic_label": "Human-readable topic name",
  "summary": "2-4 sentences: what the learner currently knows and can do on this topic, integrating prior note and this episode",
  "mastery_estimate": 0.0,
  "recurring_errors": ["..."]
}
