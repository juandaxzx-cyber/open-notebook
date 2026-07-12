"""Profile persistence over the atenea database.

The DB dependency is injectable so tests never need a live SurrealDB.
"""

from typing import Any

from tutor.db import atenea_db
from tutor.profile.models import Profile, ProfileIn


def _first_row(result: Any) -> dict[str, Any] | None:
    """Normalize a SurrealDB query result to its first row, if any."""
    if isinstance(result, list):
        rows = result
        # `query` may return a list of statement results, each a list of rows
        if rows and isinstance(rows[0], list):
            rows = rows[0]
        for row in rows:
            if isinstance(row, dict):
                return row
    return None


class ProfileService:
    async def get_profile(self, user_id: str) -> Profile | None:
        async with atenea_db() as db:
            result = await db.query(
                "SELECT * FROM profile WHERE user_id = $user_id LIMIT 1",
                {"user_id": user_id},
            )
        row = _first_row(result)
        if row is None:
            return None
        row.pop("id", None)
        return Profile.model_validate(row)

    async def upsert_profile(self, user_id: str, payload: ProfileIn) -> Profile:
        data = payload.model_dump()
        data["user_id"] = user_id
        async with atenea_db() as db:
            await db.query(
                """
                IF (SELECT * FROM profile WHERE user_id = $user_id) THEN
                    (UPDATE profile SET learning_goal = $learning_goal,
                        self_assessed_level = $self_assessed_level,
                        weekly_availability_hours = $weekly_availability_hours,
                        format_preferences = $format_preferences,
                        updated = time::now()
                     WHERE user_id = $user_id)
                ELSE
                    (CREATE profile CONTENT {
                        user_id: $user_id,
                        learning_goal: $learning_goal,
                        self_assessed_level: $self_assessed_level,
                        weekly_availability_hours: $weekly_availability_hours,
                        format_preferences: $format_preferences
                    })
                END
                """,
                data,
            )
        stored = await self.get_profile(user_id)
        assert stored is not None  # just written
        return stored
