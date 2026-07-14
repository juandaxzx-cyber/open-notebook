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
