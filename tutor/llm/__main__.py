"""Dogfood CLI: `uv run python -m tutor.llm "your prompt"`.

Proves the PR-B1 "usable when" criterion: switching TUTOR_LLM_PROVIDER /
TUTOR_LLM_MODEL alone switches the provider for the same call.
"""

import asyncio
import sys

from tutor.llm.factory import provider_from_env
from tutor.llm.interface import ChatMessage


def main() -> None:
    prompt = " ".join(sys.argv[1:]) or "Say hello in one short sentence."
    provider = provider_from_env()
    response = asyncio.run(
        provider.complete([ChatMessage(role="user", content=prompt)])
    )
    print(f"[{response.provider}:{response.model}]")
    print(response.content)


if __name__ == "__main__":
    main()
