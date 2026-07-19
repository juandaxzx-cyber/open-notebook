"""Pure retention-aware scheduling functions (PR-G3).

Replaces PR-G1's crude, count-based forgetting (`GRADUATION_REVIEWS` + a flat
`review_in_days` reschedule) with SM-2-style per-item scheduling and an
Ebbinghaus-style retention estimate for the consolidated learner-memory view.

Everything here is a pure function: no I/O, no config reads, no clock reads
(`now`/`elapsed_days` always come in as parameters). Callers resolve config
(`TUTOR_REVIEW_HORIZON_DAYS`) and the wall clock, then pass them in —
`tutor/session/store.py`'s `record_review` and the `/memories` read path
(`tutor/session/router.py`) are the two call sites (contract: "Called from
existing sites only").
"""

from __future__ import annotations

import math
from typing import Any

# Classic SM-2 default ease and its floor.
DEFAULT_EASE = 2.5
MIN_EASE = 1.3

# Default forgetting-horizon in days (env: TUTOR_REVIEW_HORIZON_DAYS) — an
# item leaves the review working-set once its newly computed interval
# exceeds this many days.
DEFAULT_HORIZON_DAYS = 60.0

# Ebbinghaus decay time-constant base (days). `retention()` models forgetting
# as an exponential decay from `mastery` with time constant
# `strength * _RETENTION_TAU_DAYS_PER_STRENGTH`. The contract does not pin a
# specific decay rate (only "mastery x Ebbinghaus decay over time since
# last_seen"), so this constant is a documented, deliberately simple design
# choice — strength=1.0 (the learner_memory schema default) gives a ~5-day
# time constant; each PR-G3 consolidation touch that bumps `strength`
# stretches the curve out, i.e. slower forgetting the more a topic has been
# reinforced.
_RETENTION_TAU_DAYS_PER_STRENGTH = 5.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def sm2_next(
    ease: float,
    interval_days: float,
    quality: float,
    horizon_days: float = DEFAULT_HORIZON_DAYS,
) -> tuple[float, float, bool]:
    """Classic SM-2 update for one reviewed item.

    `quality` is clamped to [0, 5]. The ease update is the standard SM-2
    formula (applied on every review, pass or fail), floored at 1.3:

        new_ease = ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))

    Interval: quality < 3 ("forgot it") resets the interval to 1 day.
    quality >= 3 progresses through the classic 1 -> 6 -> interval * ease
    steps. This service does not persist an explicit repetition counter
    (only `ease` and `review_interval_days`), so the step is inferred from
    the CURRENT interval — a documented smallest-reading choice, since the
    contract describes the classic progression but not how to recover the
    repetition number from stored state alone:
      * interval_days <= 0  -> first success  -> 1 day
      * interval_days <= 1  -> second success -> 6 days
      * interval_days  > 1  -> interval_days * new_ease

    Returns `(new_ease, new_interval_days, evict)`. `evict` is True when the
    new interval exceeds `horizon_days`: the caller should clear the item's
    `review_date` (it leaves the review working-set; the record itself is
    never deleted).
    """
    q = _clamp(float(quality), 0.0, 5.0)

    new_ease = ease + (0.1 - (5.0 - q) * (0.08 + (5.0 - q) * 0.02))
    new_ease = max(MIN_EASE, new_ease)

    if q < 3.0:
        new_interval = 1.0
    elif interval_days <= 0.0:
        new_interval = 1.0
    elif interval_days <= 1.0:
        new_interval = 6.0
    else:
        new_interval = interval_days * new_ease

    evict = new_interval > horizon_days
    return new_ease, new_interval, evict


def parse_quality(value: Any) -> float | None:
    """Parse one review-close quality grade from LLM output.

    Malformed or missing input (None, non-numeric, NaN) returns None so the
    caller can apply the contract's fallback: schedule with a neutral q=3 but
    NEVER evict on a parse error (interval capped at the horizon) — an LLM
    formatting hiccup must not silently graduate material out of the review
    working-set (audit fix 2026-07-19).
    """
    try:
        q = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(q):
        return None
    return _clamp(q, 0.0, 5.0)


def retention(mastery: float, strength: float, elapsed_days: float) -> float:
    """Estimated retention at read time: an Ebbinghaus-style exponential
    decay of `mastery` since the topic was last touched (`elapsed_days`),
    with a time constant proportional to `strength` (higher strength =
    slower forgetting; see `_RETENTION_TAU_DAYS_PER_STRENGTH`).

    Pure function of its three inputs; no side effects. Result clamped to
    [0, 1]. Defensive against non-positive strength/elapsed (no div-by-zero,
    no negative decay)."""
    m = _clamp(float(mastery), 0.0, 1.0)
    s = max(float(strength), 0.01)
    t = max(float(elapsed_days), 0.0)
    tau = s * _RETENTION_TAU_DAYS_PER_STRENGTH
    decay = math.exp(-t / tau)
    return _clamp(m * decay, 0.0, 1.0)
