The tutoring session below is ending. Produce its closing record.

Topic: {{topic}}
Technique used: {{technique_primary}}

Transcript:
{{transcript}}

Grounding rules (read before writing):
- Ground every statement strictly in the transcript above. Describe only what
  actually happened in it.
- Do NOT invent learner actions, answers, understanding, progress, or attitudes
  that the transcript does not evidence. If the learner never wrote something,
  do not claim they did.
- If the session was too short to assess (for example it ended before the
  learner responded, or after a single exchange), say so honestly: the summary
  and assessment must state that there is not enough evidence to assess mastery
  and that no real assessment is possible yet. Do not fabricate a rich record.
- In that case next_step should restart the session from where it stopped, so
  the learner can actually begin.
{{review_grades_instructions}}
Answer with ONLY a JSON object, no prose, in the language the learner used:
{
  "summary": "2-4 sentences: what was covered and how it went",
  "assessment": "2-3 sentences: current mastery, concrete gaps observed",
  "next_step": "one concrete next activity",
  "review_in_days": <integer 1-14: when to review this material>{{review_grades_field}}
}
