Verify this consolidated learner-memory note. Every claim in the note must
be evidenced by the tutoring episode below OR carried forward from the
learner's prior note on the topic (the note is an integration of both) —
flag anything invented, exaggerated, or supported by neither.

TOPIC: {{topic}}

Session summary: {{summary}}
Session assessment: {{assessment}}

Transcript:
{{transcript}}

Prior note on this topic (admissible evidence for carried-forward claims):
{{prior_note}}

Note to verify:
{{note}}

Grounding rules (read before judging):
- A claim is unsupported if neither the transcript/summary/assessment above
  nor the prior note actually shows it — do not give credit for plausible
  or likely progress that was never demonstrated.
- Claims of TRAJECTORY (improved, resolved an error, regressed) need the
  episode itself as evidence; the prior note alone cannot establish change.
- mastery_estimate and recurring_errors are claims too: judge whether the
  evidence supports them, not whether they sound reasonable in general.

Answer with ONLY a JSON object, no prose:
{"verdict": "pass" | "fail", "violations": ["<specific unsupported claim>", "..."]}
