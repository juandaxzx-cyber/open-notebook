Reflect on this tutoring episode and produce the learner's consolidated
memory note for the topic it covers — a durable, evolving record of how far
this learner has come on this topic (not a new per-session record; that
already exists elsewhere).

TOPIC: {{topic}}

Session summary: {{summary}}
Session assessment: {{assessment}}

Transcript:
{{transcript}}

The learner's existing memory topics — reuse a topic_key EXACTLY if this
episode is clearly the same topic as one of these; otherwise invent a new
short, stable, lowercase, hyphenated topic_key for it:
{{existing_keys}}

Additional constraints from a prior failed attempt (if any):
{{violations}}

Grounding rules (read before writing):
- Ground every claim strictly in the session summary/assessment/transcript
  above. Do not invent progress, errors, or understanding the episode does
  not evidence.
- mastery_estimate is a number from 0 to 1 reflecting the mastery of this
  topic evidenced by THIS episode — not a guess about the future.
- recurring_errors lists only misconceptions or mistakes that actually
  occurred in the episode above — omit anything not evidenced.

Answer with ONLY a JSON object, no prose:
{
  "topic_key": "stable-lowercase-slug",
  "topic_label": "Human-readable topic name",
  "summary": "2-4 sentences: what the learner currently knows and can do on this topic",
  "mastery_estimate": 0.0,
  "recurring_errors": ["..."]
}
