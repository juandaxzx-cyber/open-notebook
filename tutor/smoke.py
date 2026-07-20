"""One-command end-to-end smoke journey for the tutoring service (PR-DX2).

    python -m tutor.smoke

Default (in-process) mode drives the FULL journey over FastAPI's TestClient
against ``create_app`` with the deterministic fake LLM and an in-memory store +
profile service injected: zero config, zero keys, no SurrealDB, no OpenNotebook.

If ``TUTOR_SMOKE_BASE_URL`` is set, the SAME journey runs over real HTTP (httpx)
against a running stack; the store is then real and nothing is injected.

The journey exercises the real engine, router and models. It prints PASS/FAIL
per step and the total runtime, and exits non-zero if any step fails.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import httpx
from fastapi.testclient import TestClient

from tutor.app import create_app
from tutor.clients.open_notebook import OpenNotebookClient
from tutor.config import TutorSettings
from tutor.eval.fakes import InMemoryProfileService, InMemorySessionStore
from tutor.llm.fake import FakeProvider
from tutor.profile.models import default_user_id
from tutor.session.engine import TutorEngine
from tutor.tools.content import content_search_tool
from tutor.tools.profile_tools import profile_read_tool, profile_write_tool
from tutor.tools.registry import ToolRegistry

_SOURCE_ID = "demo"

_PROFILE = {
    "learning_goal": "linear algebra",
    "self_assessed_level": "beginner",
    "weekly_availability_hours": 5.0,
    "format_preferences": ["text", "exercises"],
}


class _CannedOpenNotebook(OpenNotebookClient):
    """Offline OpenNotebook stand-in: one indexed source, canned search rows
    tagged with a parent_id so the material-grounding leg works in-process."""

    def __init__(self) -> None:
        super().__init__(base_url="http://smoke.local")

    async def count_indexed_sources(self, page_size: int = 100) -> int:
        return 1

    async def search(
        self,
        query: str,
        limit: int = 10,
        search_type: str = "text",
        source_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "results": [
                {
                    "title": "Demo material",
                    "content": f"A short demo passage relevant to {query}.",
                    "parent_id": f"source:{_SOURCE_ID}",
                }
            ],
            "total_count": 1,
            "search_type": search_type,
        }

    async def list_sources(
        self, limit: int = 100, notebook_id: str | None = None
    ) -> list[dict[str, str]]:
        return [{"id": f"source:{_SOURCE_ID}", "title": "Demo material"}]


def build_in_process_client() -> TestClient:
    """Wire the real app with fake LLM + in-memory store/profile + canned ON."""
    profile_service = InMemoryProfileService()
    canned = _CannedOpenNotebook()

    registry = ToolRegistry()
    registry.register(content_search_tool(canned))
    registry.register(profile_read_tool(profile_service))
    registry.register(profile_write_tool(profile_service))

    engine = TutorEngine(
        llm=FakeProvider(),
        registry=registry,
        store=InMemorySessionStore(),
        user_id=default_user_id(),
        grounding_enabled=True,  # lets the source_id leg run fully offline
        memory_enabled=True,  # PR-G2: consolidate-on-close + recall-at-open
        # PR-W1: default scope/profile — FakeProvider always verifies "pass"
        # (self-verifying, since no separate verifier_llm is given here),
        # so this exercises the real gate end-to-end while staying zero-key
        # and deterministic. Ungrounded turns (no source_id) are skipped
        # under the default "grounded" scope, so the rest of the journey's
        # assertions are unaffected.
        verify_turns="grounded",
        verify_profile="high",
    )
    app = create_app(
        settings=TutorSettings(),
        client=canned,
        profile_service=profile_service,
        engine=engine,
    )
    return TestClient(app)


class _Journey:
    def __init__(self, client: Any, in_process: bool) -> None:
        self.client = client
        self.in_process = in_process
        self.steps = 0
        self.failures = 0

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.steps += 1
        if not ok:
            self.failures += 1
        mark = "PASS" if ok else "FAIL"
        suffix = f" — {detail}" if detail else ""
        print(f"[{mark}] {name}{suffix}")
        return ok

    def run(self) -> None:
        c = self.client

        r = c.get("/health")
        self.check(
            "GET /health",
            r.status_code == 200 and r.json().get("status") in {"ok", "degraded"},
            f"status={r.json().get('status')}",
        )

        r = c.put("/profile", json=_PROFILE)
        self.check(
            "PUT /profile",
            r.status_code == 200
            and r.json().get("learning_goal") == _PROFILE["learning_goal"],
        )

        r = c.get("/sessions")
        rows = r.json()
        self.check(
            "GET /sessions (empty)",
            r.status_code == 200
            and isinstance(rows, list)
            and (not self.in_process or rows == []),
            f"{len(rows) if isinstance(rows, list) else '?'} rows",
        )

        r = c.post("/session", json={"topic": "vectores"})
        body = r.json()
        sid = body.get("session_id", "")
        self.check(
            "POST /session (no source_id)",
            r.status_code == 200
            and bool(sid)
            and "[[TASK" not in body.get("opening_message", "")
            and (not self.in_process or body.get("task_index") == 1),
            f"task_index={body.get('task_index')}, technique="
            f"{(body.get('technique') or {}).get('primary')}",
        )

        r = c.post(f"/session/{sid}/message", json={"text": "mi intento es 42"})
        b1 = r.json()
        self.check(
            "POST message #1 (task/help fields present)",
            r.status_code == 200
            and all(
                k in b1
                for k in ("reply", "attempts", "help_level", "task_index", "task_label")
            ),
            f"attempts={b1.get('attempts')}, help_level={b1.get('help_level')}",
        )

        r = c.post(f"/session/{sid}/message", json={"text": "no sé, dame una pista"})
        b2 = r.json()
        self.check(
            "POST message #2 (help ladder advances)",
            r.status_code == 200 and int(b2.get("help_level", 0)) >= 1,
            f"help_level={b2.get('help_level')}",
        )

        r = c.get("/sessions")
        rows = r.json()
        mine = (
            [x for x in rows if x.get("session_id") == sid]
            if isinstance(rows, list)
            else []
        )
        self.check(
            "GET /sessions (PR-H1 tracking/progress view)",
            r.status_code == 200
            and len(mine) == 1
            and all(k in mine[0] for k in ("status", "task_index", "help_level")),
            f"status={mine[0].get('status') if mine else '?'}",
        )

        r = c.post(f"/session/{sid}/close")
        rec = r.json()
        self.check(
            "POST /session/{id}/close (record keys)",
            r.status_code == 200
            and all(
                k in rec for k in ("summary", "assessment", "next_step", "review_date")
            ),
        )

        # PR-G2: consolidate-on-close writes a durable per-topic memory note;
        # GET /memories ("Tu progreso") surfaces it.
        r = c.get("/memories")
        memories = r.json()
        self.check(
            "GET /memories (PR-G2, shows the consolidated note)",
            r.status_code == 200
            and isinstance(memories, list)
            and (not self.in_process or any(m.get("topic_label") for m in memories)),
            f"{len(memories) if isinstance(memories, list) else '?'} notes",
        )

        # PR-G3: each memory row carries a read-time estimated retention.
        self.check(
            "GET /memories rows carry estimated_retention (PR-G3)",
            not self.in_process or all("estimated_retention" in m for m in memories),
            f"{[m.get('estimated_retention') for m in memories]}",
        )

        # PR-G2: a second session on the same topic must still open cleanly —
        # recall() finds (or gracefully skips) the just-consolidated note.
        r = c.post("/session", json={"topic": "vectores"})
        second = r.json()
        self.check(
            "POST /session again on the same topic (PR-G2 recall)",
            r.status_code == 200 and bool(second.get("session_id")),
            f"session_id={second.get('session_id')}",
        )

        r = c.get("/sessions", params={"status": "closed"})
        rows = r.json()
        self.check(
            "GET /sessions?status=closed (shows closed)",
            r.status_code == 200
            and isinstance(rows, list)
            and any(x.get("session_id") == sid for x in rows),
        )

        r = c.get("/reviews/due")
        due = r.json()
        self.check(
            "GET /reviews/due",
            r.status_code == 200 and isinstance(due, list),
            f"{len(due) if isinstance(due, list) else '?'} due",
        )

        r = c.get(f"/session/{sid}")
        rec = r.json()
        self.check(
            "GET /session/{id} (record)",
            r.status_code == 200
            and rec.get("status") == "closed"
            and rec.get("topic") == "vectores",
        )

        # Material-grounding leg. Fully exercised offline in-process (canned
        # source); over real HTTP it depends on the running stack's grounding
        # config, so there we only require a successful open.
        r = c.post("/session", json={"topic": "svd", "source_id": _SOURCE_ID})
        gbody = r.json()
        if self.in_process:
            self.check(
                "POST /session with source_id (grounded, in-process)",
                r.status_code == 200 and gbody.get("source_id") == _SOURCE_ID,
                f"source_id={gbody.get('source_id')}",
            )
        else:
            self.check(
                "POST /session with source_id (stack grounding)",
                r.status_code == 200 and bool(gbody.get("session_id")),
                "grounding depends on the running stack",
            )

        # PR-W1: the grounded opening turn above was gated (scope="grounded"
        # in build_in_process_client) and FakeProvider always self-verifies
        # "pass", so the outcome must be "clean" — zero-key, deterministic
        # proof the verify-before-send gate runs end-to-end.
        self.check(
            "POST /session with source_id carries a clean verification outcome (PR-W1)",
            not self.in_process or gbody.get("verification_outcome") == "clean",
            f"verification_outcome={gbody.get('verification_outcome')}",
        )


def run(base_url: str | None = None) -> int:
    """Run the journey; return a process exit code (0 = all steps passed)."""
    start = time.monotonic()
    if base_url:
        mode = f"real HTTP ({base_url})"
        client: Any = httpx.Client(base_url=base_url, timeout=30.0)
        in_process = False
    else:
        mode = "in-process (TestClient + fake LLM + in-memory store)"
        client = build_in_process_client()
        in_process = True

    print(f"== tutor smoke — {mode} ==")
    journey = _Journey(client, in_process)
    try:
        journey.run()
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    elapsed = time.monotonic() - start
    print(
        f"\n{journey.steps} steps, {journey.failures} failed, "
        f"{elapsed:.2f}s total — "
        f"{'PASS' if journey.failures == 0 else 'FAIL'}"
    )
    return 1 if journey.failures else 0


def main() -> None:
    sys.exit(run(os.environ.get("TUTOR_SMOKE_BASE_URL") or None))


if __name__ == "__main__":
    main()
