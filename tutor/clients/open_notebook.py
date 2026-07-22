"""Thin async client over OpenNotebook's REST API.

Auth model (verified in api/auth.py): when OPEN_NOTEBOOK_PASSWORD is set,
every /api/* request requires `Authorization: Bearer <password>`; when unset,
the API is open. Endpoint paths verified in api/main.py and api/routers/.
"""

from typing import Any, Literal

import httpx


class OpenNotebookClient:
    """Minimal client for the OpenNotebook REST API."""

    def __init__(
        self,
        base_url: str,
        password: str | None = None,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._password = password
        self._timeout = timeout
        self._transport = transport  # injectable for tests

    def _headers(self) -> dict[str, str]:
        if self._password:
            return {"Authorization": f"Bearer {self._password}"}
        return {}

    async def count_indexed_sources(self, page_size: int = 100) -> int:
        """Return the number of indexed sources (capped at `page_size`).

        Uses GET /api/sources, which returns a JSON list. A capped count is
        enough for the healthcheck contract (indexed_sources >= 1).
        """
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            response = await client.get(
                f"{self._base_url}/api/sources",
                params={"limit": page_size, "offset": 0},
                headers=self._headers(),
            )
            response.raise_for_status()
            sources = response.json()
            return len(sources)

    async def search(
        self,
        query: str,
        limit: int = 10,
        search_type: Literal["text", "vector"] = "text",
        source_id: str | None = None,
    ) -> dict[str, Any]:
        """Search sources and notes via POST /api/search.

        Request/response shapes verified in api/models.py (SearchRequest /
        SearchResponse: results, total_count, search_type).

        ``source_id`` (PR-M2) is included in the request body only when set,
        so unscoped callers send the exact same payload as before. The core
        API matches it DB-side inside ``fn::vector_search``; it is ignored
        for text search.
        """
        payload: dict[str, Any] = {"query": query, "type": search_type, "limit": limit}
        if source_id:
            payload["source_id"] = source_id
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            response = await client.post(
                f"{self._base_url}/api/search",
                json=payload,
                headers=self._headers(),
            )
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result

    async def list_sources(
        self, limit: int = 100, notebook_id: str | None = None
    ) -> list[dict[str, str]]:
        """List indexed sources (id + title) for the material picker (PR-M1).

        Uses GET /api/sources. Returns a compact shape the UI can render; the
        full source body is never pulled here.
        """
        params: dict[str, Any] = {"limit": limit, "offset": 0}
        if notebook_id:
            params["notebook_id"] = notebook_id
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            response = await client.get(
                f"{self._base_url}/api/sources",
                params=params,
                headers=self._headers(),
            )
            response.raise_for_status()
            sources = response.json()
        return [
            {"id": str(item.get("id")), "title": str(item.get("title") or "")}
            for item in sources
            if isinstance(item, dict)
        ]

    async def get_source(self, source_id: str) -> dict[str, Any]:
        """Fetch one source's full record, including ``full_text`` (PR-W1
        whole-source-lite; the ``get_source`` capability was pulled forward
        from the parked M3 slice per the W1 contract).

        Uses GET /api/sources/{id} (api/routers/sources.py::get_source),
        which returns full_text on ``SourceResponse``.
        """
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            response = await client.get(
                f"{self._base_url}/api/sources/{source_id}",
                headers=self._headers(),
            )
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result

    async def create_source_from_file(
        self,
        filename: str,
        content: bytes,
        content_type: str | None = None,
        *,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Upload a file as a new source via POST /api/sources (multipart;
        PR-BT3: testers upload material through the tutor, never touching
        OpenNotebook directly).

        Uses the existing async processing path (``async_processing=true``,
        api/routers/sources.py::create_source /
        ``parse_source_form_data``) so the request returns as soon as
        OpenNotebook has queued the job, instead of blocking on extraction —
        the same tradeoff the multipart endpoint already offers today.
        """
        data: dict[str, str] = {"type": "upload", "async_processing": "true"}
        if title:
            data["title"] = title
        files = {
            "file": (filename, content, content_type or "application/octet-stream")
        }
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            response = await client.post(
                f"{self._base_url}/api/sources",
                data=data,
                files=files,
                headers=self._headers(),
            )
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result

    async def create_source_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a source from a JSON payload (url or text content) via
        POST /api/sources/json (PR-BT3: testers create link/text sources
        through the tutor). ``payload`` is forwarded as-is — the caller
        (``tutor/app.py``) builds the ``SourceCreate``-shaped body."""
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            response = await client.post(
                f"{self._base_url}/api/sources/json",
                json=payload,
                headers=self._headers(),
            )
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            return result
