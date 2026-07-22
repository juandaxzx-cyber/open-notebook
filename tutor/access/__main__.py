"""Tester provisioning CLI: `python -m tutor.access` (PR-BT2 contract;
`share` added PR-BT3).

Direct SurrealDB access via `tutor.auth.AccessTokenStore` /
`tutor.usage.UsageCounterStore` / `tutor.ownership.SourceOwnerStore` — no
HTTP. This CLI runs on the server host (the developer's machine or the
deploy box), not through the public API; there are no admin endpoints in
this slice (playbook BT2 pre-pinned facts). Same "direct store access"
pattern as `tutor/tools/__main__.py`, unlike the HTTP-wizard pattern of
`tutor/profile/__main__.py`.

    python -m tutor.access create <user_id> [--label LABEL]
    python -m tutor.access list
    python -m tutor.access revoke <user_id_or_label>
    python -m tutor.access usage
    python -m tutor.access share <source_id>

The pure formatting/aggregation helpers below (`build_magic_link`,
`aggregate_usage`, `format_token_row`) are unit-tested directly; the I/O
wrappers that touch the real stores are dogfood-verified (same split as
`tutor/tools/__main__.py` — the store CRUD itself needs a live SurrealDB, so
only the store methods have DB-shaped contracts, tested via fakes, per
`tests_tutor/test_auth.py`, `tests_tutor/test_usage.py` and
`tests_tutor/test_ownership.py`).
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from dotenv import load_dotenv

from tutor.auth import AccessTokenStore
from tutor.config import TutorSettings
from tutor.ownership import SourceOwnerStore
from tutor.usage import UsageCounterStore, today_utc


def build_magic_link(public_url: str, raw_token: str) -> str:
    """`<public_url>/?t=<token>` — matches the UI's `?t=` magic-link landing
    (PR-BT1, `tutor/ui/index.html::initAuthToken`)."""
    return f"{public_url.rstrip('/')}/?t={raw_token}"


def format_token_row(row: dict[str, Any]) -> str:
    status = "revoked" if row.get("revoked") else "active"
    label = row.get("label") or ""
    return (
        f"{row.get('user_id')}\t{status}\tlabel={label!r}\t"
        f"created={row.get('created')}\tid={row.get('id')}"
    )


def aggregate_usage(
    rows: list[dict[str, Any]], today: str
) -> dict[str, dict[str, int]]:
    """Raw `(user_id, day, turns)` rows -> per-user `{total, today}` turn
    counts (the `usage` CLI verb's "per-user turn counts", contract)."""
    totals: dict[str, dict[str, int]] = {}
    for row in rows:
        user_id = str(row.get("user_id"))
        turns = int(row.get("turns") or 0)
        entry = totals.setdefault(user_id, {"total": 0, "today": 0})
        entry["total"] += turns
        if row.get("day") == today:
            entry["today"] += turns
    return totals


async def _create(user_id: str, label: str) -> None:
    store = AccessTokenStore()
    raw = await store.create(user_id, label)
    settings = TutorSettings.from_env()
    link = build_magic_link(settings.public_url, raw)
    suffix = f" ({label})" if label else ""
    print(f"Tester '{user_id}' provisioned{suffix}.")
    print("Magic link (shown once, send it to the tester):")
    print(link)


async def _list() -> None:
    store = AccessTokenStore()
    rows = await store.list_all()
    if not rows:
        print("No tokens provisioned yet.")
        return
    for row in rows:
        print(format_token_row(row))


async def _revoke(user_id_or_label: str) -> None:
    store = AccessTokenStore()
    count = await store.revoke(user_id_or_label)
    if count:
        print(f"Revoked {count} token(s) matching '{user_id_or_label}'.")
    else:
        print(f"No active token found matching '{user_id_or_label}'.")


async def _usage() -> None:
    store = UsageCounterStore()
    rows = await store.usage()
    if not rows:
        print("No usage recorded yet.")
        return
    totals = aggregate_usage(rows, today_utc())
    for user_id in sorted(totals):
        entry = totals[user_id]
        print(f"{user_id}\ttotal={entry['total']}\ttoday={entry['today']}")


async def _share(source_id: str) -> None:
    """`tutor.access share <source_id>` (PR-BT3): flip a private source's
    `public` flag to true. A source with no ownership row is already public
    (grandfather clause) — reported as a no-op, not an error."""
    store = SourceOwnerStore()
    changed = await store.share(source_id)
    if changed:
        print(f"Source '{source_id}' is now public.")
    else:
        print(
            f"Source '{source_id}' is already public "
            "(no private ownership row, or already shared)."
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tutor.access", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    create_p = sub.add_parser("create", help="Provision a new tester")
    create_p.add_argument("user_id")
    create_p.add_argument("--label", default="")

    sub.add_parser("list", help="List provisioned testers")

    revoke_p = sub.add_parser("revoke", help="Revoke a tester's token(s)")
    revoke_p.add_argument("user_id_or_label")

    sub.add_parser("usage", help="Per-user turn counts")

    share_p = sub.add_parser("share", help="Make a private source public")
    share_p.add_argument("source_id")
    return parser


def main() -> None:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "create":
        asyncio.run(_create(args.user_id, args.label))
    elif args.command == "list":
        asyncio.run(_list())
    elif args.command == "revoke":
        asyncio.run(_revoke(args.user_id_or_label))
    elif args.command == "usage":
        asyncio.run(_usage())
    elif args.command == "share":
        asyncio.run(_share(args.source_id))


if __name__ == "__main__":
    main()
