"""Thin async client over OpenNotebook's REST API.

Auth model (verified in api/auth.py): when OPEN_NOTEBOOK_PASSWORD is set,
every /api/* request requires `Authorization: Bearer <password>`; when unset,
the API is open. Endpoint paths verified in api/main.py and api/routers/.
"""

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
