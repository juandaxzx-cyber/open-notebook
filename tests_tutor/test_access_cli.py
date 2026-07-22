"""Unit tests for tutor/access/__main__.py (PR-BT2 CLI): pure helpers
(link building, row formatting, usage aggregation) and argparse wiring for
`create`/`list`/`revoke`/`usage`. No network/DB — the I/O wrappers that
touch the real stores are dogfood-verified, same split as
`tutor/tools/__main__.py` (untested at the `main()` level; D1 precedent)."""

from __future__ import annotations

from tutor.access.__main__ import (
    aggregate_usage,
    build_magic_link,
    build_parser,
    format_token_row,
)

# --- build_magic_link ---


def test_build_magic_link_appends_query_param() -> None:
    link = build_magic_link("http://localhost:5056", "raw-token-123")
    assert link == "http://localhost:5056/?t=raw-token-123"


def test_build_magic_link_strips_trailing_slash() -> None:
    link = build_magic_link("https://atenea.example.com/", "abc")
    assert link == "https://atenea.example.com/?t=abc"


# --- format_token_row ---


def test_format_token_row_active() -> None:
    row = {
        "user_id": "alice",
        "label": "beta-1",
        "created": "2026-07-20T00:00:00Z",
        "id": "access_token:abc",
        "revoked": False,
    }
    line = format_token_row(row)
    assert "alice" in line
    assert "active" in line
    assert "revoked" not in line.split("\t")[1]  # status column itself is "active"
    assert "beta-1" in line


def test_format_token_row_revoked() -> None:
    row = {
        "user_id": "bob",
        "label": "",
        "created": "2026-07-20T00:00:00Z",
        "id": "access_token:def",
        "revoked": True,
    }
    line = format_token_row(row)
    assert "bob" in line
    assert "\trevoked\t" in line


# --- aggregate_usage ---


def test_aggregate_usage_sums_per_user_and_flags_today() -> None:
    rows = [
        {"user_id": "alice", "day": "2026-07-20", "turns": 3},
        {"user_id": "alice", "day": "2026-07-19", "turns": 5},
        {"user_id": "bob", "day": "2026-07-20", "turns": 2},
    ]
    totals = aggregate_usage(rows, today="2026-07-20")
    assert totals["alice"] == {"total": 8, "today": 3}
    assert totals["bob"] == {"total": 2, "today": 2}


def test_aggregate_usage_empty_rows() -> None:
    assert aggregate_usage([], today="2026-07-20") == {}


def test_aggregate_usage_no_rows_for_today_still_totals() -> None:
    rows = [{"user_id": "alice", "day": "2026-07-01", "turns": 10}]
    totals = aggregate_usage(rows, today="2026-07-20")
    assert totals["alice"] == {"total": 10, "today": 0}


# --- CLI argument parsing ---


def test_parser_create_requires_user_id_and_accepts_label() -> None:
    parser = build_parser()
    args = parser.parse_args(["create", "alice", "--label", "beta-1"])
    assert args.command == "create"
    assert args.user_id == "alice"
    assert args.label == "beta-1"


def test_parser_create_label_defaults_to_empty() -> None:
    parser = build_parser()
    args = parser.parse_args(["create", "alice"])
    assert args.label == ""


def test_parser_list() -> None:
    parser = build_parser()
    args = parser.parse_args(["list"])
    assert args.command == "list"


def test_parser_revoke_requires_key() -> None:
    parser = build_parser()
    args = parser.parse_args(["revoke", "alice"])
    assert args.command == "revoke"
    assert args.user_id_or_label == "alice"


def test_parser_usage() -> None:
    parser = build_parser()
    args = parser.parse_args(["usage"])
    assert args.command == "usage"


def test_parser_requires_a_subcommand() -> None:
    import pytest

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_build_parser_share_takes_source_id() -> None:
    # PR-BT3: `share <source_id>` flips a private source to public.
    parser = build_parser()
    args = parser.parse_args(["share", "source:abc123"])
    assert args.command == "share"
    assert args.source_id == "source:abc123"
