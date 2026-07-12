"""Dogfood CLI for the tool registry.

Usage:
    uv run python -m tutor.tools              # list registered tools
    uv run python -m tutor.tools call <name> '<json-args>'
"""

import asyncio
import json
import sys

from tutor.tools.defaults import build_default_registry


def main() -> None:
    registry = build_default_registry()
    argv = sys.argv[1:]

    if not argv or argv[0] == "list":
        for spec in registry.list_specs():
            print(f"{spec['name']}: {spec['description']}")
        return

    if argv[0] == "call" and len(argv) >= 2:
        name = argv[1]
        arguments = json.loads(argv[2]) if len(argv) > 2 else {}
        result = asyncio.run(registry.call(name, arguments))
        print(json.dumps(result, indent=2, default=str))
        return

    print(__doc__)
    sys.exit(1)


if __name__ == "__main__":
    main()
