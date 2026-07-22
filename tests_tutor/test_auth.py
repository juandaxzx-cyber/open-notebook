"""Unit tests for tutor/auth.py (PR-BT1): hash round-trip, resolution order,
401 paths, auth-off lock. No network/DB — `AccessTokenStoreProtocol` is
satisfied by a small in-memory fake, same pattern as the other store
protocols in this codebase (`memory.MemoryStoreProtocol`)."""

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException

from tutor.auth import (
    build_resolve_user,
    default_resolve_user,
    generate_token,
    hash_token,
)
from tutor.config import TutorSettings
from tutor.profile.models import default_user_id


class FakeAccessTokenStore:
    def __init__(self, rows: dict[str, dict[str, Any]] | None = None) -> None:
        self._rows = rows or {}

    async def get_by_hash(self, token_hash: str) -> dict[str, Any] | None:
        return self._rows.get(token_hash)


# --- hash_token / generate_token ---


def test_hash_token_is_deterministic_sha256_hex() -> None:
    h1 = hash_token("a-raw-token")
    h2 = hash_token("a-raw-token")
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex digest length
    assert all(c in "0123456789abcdef" for c in h1)
    assert h1 != "a-raw-token"  # never the raw value itself


def test_hash_token_differs_for_different_input() -> None:
    assert hash_token("token-a") != hash_token("token-b")


def test_generate_token_is_unique_and_urlsafe() -> None:
    a, b = generate_token(), generate_token()
    assert a != b
    assert len(a) > 20
    assert all(c.isalnum() or c in "-_" for c in a)


# --- resolve_user: auth-off lock (byte-identical to pre-BT1) ---


def test_resolve_user_auth_off_returns_default_user_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TUTOR_USER_ID", "juanda")
    resolve = build_resolve_user(
        TutorSettings(auth_enabled=False), FakeAccessTokenStore()
    )
    result = asyncio.run(resolve(authorization=None, t=None))
    assert result == "juanda" == default_user_id()


def test_resolve_user_auth_off_ignores_any_token_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Lock test (M1-style): with auth off, even a garbage/well-formed token
    # never changes the outcome and the store is never consulted.
    monkeypatch.setenv("TUTOR_USER_ID", "juanda")

    class ExplodingStore:
        async def get_by_hash(self, token_hash: str) -> dict[str, Any] | None:
            raise AssertionError("auth-off must never touch the token store")

    resolve = build_resolve_user(TutorSettings(auth_enabled=False), ExplodingStore())
    result = asyncio.run(resolve(authorization="Bearer garbage", t="also-garbage"))
    assert result == "juanda"


# --- resolve_user: resolution order (auth on) ---


def test_resolve_user_prefers_bearer_header_over_query_param() -> None:
    store = FakeAccessTokenStore(
        {
            hash_token("header-token"): {"user_id": "alice", "revoked": False},
            hash_token("query-token"): {"user_id": "bob", "revoked": False},
        }
    )
    resolve = build_resolve_user(TutorSettings(auth_enabled=True), store)
    result = asyncio.run(resolve(authorization="Bearer header-token", t="query-token"))
    assert result == "alice"


def test_resolve_user_falls_back_to_query_param_when_no_header() -> None:
    store = FakeAccessTokenStore(
        {hash_token("query-token"): {"user_id": "bob", "revoked": False}}
    )
    resolve = build_resolve_user(TutorSettings(auth_enabled=True), store)
    result = asyncio.run(resolve(authorization=None, t="query-token"))
    assert result == "bob"


def test_resolve_user_ignores_non_bearer_scheme_and_falls_back_to_query() -> None:
    store = FakeAccessTokenStore(
        {hash_token("query-token"): {"user_id": "bob", "revoked": False}}
    )
    resolve = build_resolve_user(TutorSettings(auth_enabled=True), store)
    result = asyncio.run(resolve(authorization="Basic dXNlcjpwYXNz", t="query-token"))
    assert result == "bob"


# --- resolve_user: 401 paths (auth on) ---


def test_resolve_user_401_when_no_token_given() -> None:
    resolve = build_resolve_user(
        TutorSettings(auth_enabled=True), FakeAccessTokenStore()
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(resolve(authorization=None, t=None))
    assert exc.value.status_code == 401


def test_resolve_user_401_when_token_unknown() -> None:
    resolve = build_resolve_user(
        TutorSettings(auth_enabled=True), FakeAccessTokenStore()
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(resolve(authorization="Bearer does-not-exist", t=None))
    assert exc.value.status_code == 401


def test_resolve_user_401_when_token_revoked() -> None:
    store = FakeAccessTokenStore(
        {hash_token("revoked-token"): {"user_id": "alice", "revoked": True}}
    )
    resolve = build_resolve_user(TutorSettings(auth_enabled=True), store)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(resolve(authorization="Bearer revoked-token", t=None))
    assert exc.value.status_code == 401


def test_resolve_user_valid_unrevoked_token_resolves_its_user() -> None:
    store = FakeAccessTokenStore(
        {hash_token("good-token"): {"user_id": "alice", "revoked": False}}
    )
    resolve = build_resolve_user(TutorSettings(auth_enabled=True), store)
    result = asyncio.run(resolve(authorization="Bearer good-token", t=None))
    assert result == "alice"


# --- default_resolve_user (standalone-router fallback) ---


def test_default_resolve_user_returns_default_user_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TUTOR_USER_ID", "juanda")
    resolve = default_resolve_user()
    assert asyncio.run(resolve()) == "juanda"
