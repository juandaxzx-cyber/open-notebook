"""Questionnaire wizard: `uv run python -m tutor.profile`.

Asks the four PR-C1 questions and PUTs them to the running tutor service
(API-first: the wizard is just another API consumer).
"""

import httpx
from dotenv import load_dotenv

from tutor.config import TutorSettings
from tutor.profile.models import ProfileIn


def ask_questions() -> ProfileIn:
    print("Atenea — initial questionnaire (4 questions)\n")
    goal = input("1/4 What do you want to learn (your current goal)? ").strip()
    level = input("2/4 How would you rate your current level in it? ").strip()
    hours = float(input("3/4 How many hours per week can you invest? ").strip())
    formats_raw = input(
        "4/4 Preferred formats (comma-separated: text, video, audio, exercises...)? "
    ).strip()
    formats = [f.strip() for f in formats_raw.split(",") if f.strip()]
    return ProfileIn(
        learning_goal=goal,
        self_assessed_level=level,
        weekly_availability_hours=hours,
        format_preferences=formats,
    )


def main() -> None:
    load_dotenv()
    settings = TutorSettings.from_env()
    payload = ask_questions()
    base = f"http://localhost:{settings.port}"
    response = httpx.put(f"{base}/profile", json=payload.model_dump(), timeout=10.0)
    response.raise_for_status()
    print("\nProfile stored:")
    print(response.json())


if __name__ == "__main__":
    main()
