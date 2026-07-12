from fastapi.testclient import TestClient

from tutor.app import create_app
from tutor.config import TutorSettings
from tutor.profile.models import Profile, ProfileIn
from tutor.profile.service import ProfileService, _first_row


class FakeProfileService(ProfileService):
    def __init__(self) -> None:
        self.stored: dict[str, Profile] = {}

    async def get_profile(self, user_id: str) -> Profile | None:
        return self.stored.get(user_id)

    async def upsert_profile(self, user_id: str, payload: ProfileIn) -> Profile:
        profile = Profile(user_id=user_id, **payload.model_dump())
        self.stored[user_id] = profile
        return profile


def _client(service: FakeProfileService) -> TestClient:
    app = create_app(settings=TutorSettings(), profile_service=service)
    return TestClient(app)


def test_get_profile_404_before_questionnaire() -> None:
    response = _client(FakeProfileService()).get("/profile")
    assert response.status_code == 404


def test_put_then_get_profile_with_user_id(monkeypatch) -> None:
    monkeypatch.setenv("TUTOR_USER_ID", "juanda")
    client = _client(FakeProfileService())

    payload = {
        "learning_goal": "linear algebra",
        "self_assessed_level": "beginner",
        "weekly_availability_hours": 5.0,
        "format_preferences": ["text", "exercises"],
    }
    put_response = client.put("/profile", json=payload)
    assert put_response.status_code == 200
    assert put_response.json()["user_id"] == "juanda"

    get_response = client.get("/profile")
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["learning_goal"] == "linear algebra"
    assert body["format_preferences"] == ["text", "exercises"]


def test_put_profile_validates_payload() -> None:
    client = _client(FakeProfileService())
    response = client.put(
        "/profile",
        json={
            "learning_goal": "",
            "self_assessed_level": "x",
            "weekly_availability_hours": -1,
        },
    )
    assert response.status_code == 422


def test_first_row_normalizes_nested_results() -> None:
    assert _first_row([[{"a": 1}]]) == {"a": 1}
    assert _first_row([{"a": 1}, {"b": 2}]) == {"a": 1}
    assert _first_row([[]]) is None
    assert _first_row([]) is None
    assert _first_row(None) is None
