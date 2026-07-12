from fastapi.testclient import TestClient

from tutor.app import create_app
from tutor.config import TutorSettings


def test_root_serves_chat_page() -> None:
    app = create_app(settings=TutorSettings())
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert "Atenea" in body
    assert "/session" in body  # talks to the session endpoints
