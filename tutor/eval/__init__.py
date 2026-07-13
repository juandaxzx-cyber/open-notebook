"""Prompt-evaluation harness (PR-E2 part b).

Runs scripted learner personas against the real TutorEngine + real LLM (with
in-memory fakes for registry and store), then scores the transcripts with an
LLM judge applying the evidence-based rubric one criterion at a time.
Evidence base: docs/atenea/tutor_pedagogy_evidence.md.
"""
