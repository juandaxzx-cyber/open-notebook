from fastapi.testclient import TestClient

from tutor.app import create_app
from tutor.clients.open_notebook import OpenNotebookClient
from tutor.config import TutorSettings


class FakeOpenNotebookClient(OpenNotebookClient):
    def __init__(
        self, count: int | None = None, error: Exception | None = None
    ) -> None:
        super().__init__(base_url="http://unused")
        self._count = count
        self._error = error

    async def count_indexed_sources(self, page_size: int = 100) -> int:
        if self._error is not None:
            raise self._error
        assert self._count is not None
        return self._count


def test_health_ok_with_indexed_sources() -> None:
    app = create_app(settings=TutorSettings(), client=FakeOpenNotebookClient(count=3))
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["open_notebook"]["reachable"] is True
    assert body["open_notebook"]["indexed_sources"] == 3


def test_health_degraded_when_open_notebook_unreachable() -> None:
    app = create_app(
        settings=TutorSettings(),
        client=FakeOpenNotebookClient(error=RuntimeError("connection refused")),
    )
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["open_notebook"]["reachable"] is False
    assert "connection refused" in body["open_notebook"]["error"]
