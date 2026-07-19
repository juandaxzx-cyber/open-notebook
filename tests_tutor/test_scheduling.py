"""PR-G3 — retention-aware forgetting: table tests for the pure SM-2 /
retention / grade-parsing functions in `tutor.session.scheduling`."""

from __future__ import annotations

import math

import pytest

from tutor.session.scheduling import parse_quality, retention, sm2_next

# --- sm2_next: progression (1 -> 6 -> interval * ease) ---


def test_sm2_first_success_from_fresh_item_sets_interval_to_one_day() -> None:
    ease, interval, evict = sm2_next(2.5, 0.0, 4.0)
    assert interval == 1.0
    assert evict is False
    assert ease == pytest.approx(2.5)  # q=4 -> zero ease delta


def test_sm2_second_success_advances_interval_to_six_days() -> None:
    ease, interval, evict = sm2_next(2.5, 1.0, 4.0)
    assert interval == 6.0
    assert evict is False


def test_sm2_third_success_multiplies_interval_by_new_ease() -> None:
    ease, interval, evict = sm2_next(2.5, 6.0, 5.0)
    assert ease == pytest.approx(2.6)  # q=5 -> +0.1
    assert interval == pytest.approx(6.0 * 2.6)
    assert evict is False


# --- sm2_next: penalty + reset on quality < 3 ---


def test_sm2_low_quality_resets_interval_to_one_day() -> None:
    ease, interval, evict = sm2_next(2.6, 15.6, 0.0)
    assert interval == 1.0
    assert evict is False


def test_sm2_low_quality_penalizes_ease() -> None:
    ease, _interval, _evict = sm2_next(2.6, 15.6, 0.0)
    assert ease < 2.6  # penalized relative to the input ease
    assert ease == pytest.approx(2.6 - 0.8)


def test_sm2_ease_never_drops_below_the_1_3_floor() -> None:
    ease, _interval, _evict = sm2_next(1.3, 1.0, 0.0)
    assert ease == pytest.approx(1.3)


# --- sm2_next: quality clamped to [0, 5] ---


def test_sm2_quality_above_five_is_clamped() -> None:
    assert sm2_next(2.5, 6.0, 7.0) == sm2_next(2.5, 6.0, 5.0)


def test_sm2_quality_below_zero_is_clamped() -> None:
    assert sm2_next(2.5, 6.0, -3.0) == sm2_next(2.5, 6.0, 0.0)


# --- sm2_next: horizon eviction ---


def test_sm2_evicts_when_new_interval_exceeds_default_horizon() -> None:
    _ease, interval, evict = sm2_next(2.5, 30.0, 5.0)
    assert interval > 60.0
    assert evict is True


def test_sm2_does_not_evict_within_a_wider_horizon() -> None:
    _ease, interval, evict = sm2_next(2.5, 30.0, 5.0, horizon_days=100.0)
    assert interval <= 100.0
    assert evict is False


def test_sm2_reset_after_failure_never_evicts() -> None:
    # Even an item on a huge interval that fails resets to 1 day, well under
    # any sane horizon — reset (quality < 3) never evicts.
    _ease, interval, evict = sm2_next(2.5, 500.0, 1.0, horizon_days=60.0)
    assert interval == 1.0
    assert evict is False


# --- parse_quality: grade parsing / fallback ---


def test_parse_quality_accepts_a_plain_number() -> None:
    assert parse_quality(4) == 4.0
    assert parse_quality(4.0) == 4.0


def test_parse_quality_accepts_a_numeric_string() -> None:
    assert parse_quality("4") == 4.0


def test_parse_quality_clamps_out_of_range_values() -> None:
    assert parse_quality(7) == 5.0
    assert parse_quality(-2) == 0.0


def test_parse_quality_returns_none_on_missing_value() -> None:
    assert parse_quality(None) is None


def test_parse_quality_returns_none_on_malformed_value() -> None:
    # None signals the caller to apply the no-evict fallback (audit fix).
    assert parse_quality("not a number") is None
    assert parse_quality({"nope": True}) is None


def test_parse_quality_returns_none_on_nan() -> None:
    assert parse_quality(float("nan")) is None


# --- retention: Ebbinghaus-style decay ---


def test_retention_at_zero_elapsed_equals_mastery() -> None:
    assert retention(0.8, 1.0, 0.0) == pytest.approx(0.8)


def test_retention_decays_with_elapsed_time() -> None:
    r0 = retention(0.8, 1.0, 0.0)
    r5 = retention(0.8, 1.0, 5.0)
    r20 = retention(0.8, 1.0, 20.0)
    assert r5 < r0
    assert r20 < r5
    assert r20 >= 0.0


def test_retention_matches_ebbinghaus_exponential_formula() -> None:
    # documented time constant: tau = strength * 5.0 days
    expected = 0.8 * math.exp(-5.0 / 5.0)
    assert retention(0.8, 1.0, 5.0) == pytest.approx(expected)


def test_retention_higher_strength_decays_more_slowly() -> None:
    weak = retention(0.8, 1.0, 10.0)
    strong = retention(0.8, 5.0, 10.0)
    assert strong > weak


def test_retention_is_clamped_to_zero_one() -> None:
    assert 0.0 <= retention(1.5, 1.0, 0.0) <= 1.0  # mastery out of range
    assert 0.0 <= retention(0.8, 1.0, -10.0) <= 1.0  # negative elapsed defensive
    assert retention(0.8, 1.0, -10.0) == pytest.approx(0.8)  # treated as elapsed=0
