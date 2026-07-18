Verify this consolidated learner-memory note against the tutoring episode it
claims to summarize. Every claim in the note must be evidenced by the
episode below — flag anything invented, exaggerated, or unsupported.

TOPIC: {{topic}}

Session summary: {{summary}}
Session assessment: {{assessment}}

Transcript:
{{transcript}}

Note to verify:
{{note}}

Grounding rules (read before judging):
- A claim is unsupported if the transcript/summary/assessment above does
  not actually show it happening — do not give credit for plausible or
  likely progress that was never demonstrated.
- mastery_estimate and recurring_errors are claims too: judge whether the
  episode evidences them, not whether they sound reasonable in general.

Answer with ONLY a JSON object, no prose:
{"verdict": "pass" | "fail", "violations": ["<specific unsupported claim>", "..."]}
