"""Pricing lookup and cost computation for the OpenCode Token Tracker.

Prices are USD per 1M tokens. A model key has the form `provider/model`
(e.g. `opencode/deepseek-v4-flash-free`). An explicit entry in the pricing
dict always wins; a model whose id ends with `-free` is free at $0 when no
explicit price exists.
"""

from __future__ import annotations

from typing import Protocol

from tracker.config import Price

# Token counts at which format_tokens switches to K/M/B suffixes.
_K_THRESHOLD = 10_000
_M_THRESHOLD = 1_000_000
_B_THRESHOLD = 1_000_000_000


class Session(Protocol):
    """Minimal session contract needed for cost computation.

    `tracker.store` owns the real Session; this protocol keeps pricing.py
    independent of it. `model_key` is the `provider/model` key used for
    pricing lookup; `tokens` maps the five bucket names (`input`, `output`,
    `reasoning`, `cache_read`, `cache_write`) to counts; `cost_db` is the
    cost recorded in the database, used as a fallback when the model has no
    known price.
    """

    model_key: str
    tokens: dict[str, int]
    cost_db: float


def price_for(model_key: str, pricing: dict[str, Price]) -> Price | None:
    """Return the price for `model_key`, or None when it is unknown.

    An exact `provider/model` match in `pricing` always wins. Otherwise a
    model whose id ends with `-free` is free at $0; anything else is
    unpriced.
    """
    if model_key in pricing:
        return pricing[model_key]
    model_id = model_key.rsplit("/", 1)[-1]
    if model_id.endswith("-free"):
        return Price(0.0, 0.0, 0.0, 0.0)
    return None


def compute_cost(session: Session, pricing: dict[str, Price]) -> tuple[float, bool]:
    """Compute a session's cost in USD from its token buckets.

    Returns `(cost, unpriced)`. Cost is the sum of each bucket times its
    per-1M price, divided by 1_000_000; reasoning tokens are priced as
    input. When the model has no price, the database-recorded cost
    (`session.cost_db`) is returned when positive, otherwise 0.0 —
    `unpriced` is True in both cases.
    """
    price = price_for(session.model_key, pricing)
    if price is None:
        if session.cost_db > 0:
            return (session.cost_db, True)
        return (0.0, True)
    tokens = session.tokens
    cost = (
        tokens["input"] * price.input
        + tokens["output"] * price.output
        + tokens["reasoning"] * price.input
        + tokens["cache_read"] * price.cache_read
        + tokens["cache_write"] * price.cache_write
    ) / 1_000_000
    return (cost, False)


def format_tokens(n: int) -> str:
    """Format a token count for humans: `1.2B`, `1.2M`, `585K`, `1234`.

    Counts at or above 1_000_000_000 use a B suffix, counts at or above
    1_000_000 use an M suffix, counts at or above 10_000 use a K suffix —
    each with one decimal that is dropped when it is zero; smaller counts
    are printed as-is.
    """
    if n >= _B_THRESHOLD:
        return _with_suffix(n / 1_000_000_000, "B")
    if n >= _M_THRESHOLD:
        return _with_suffix(n / 1_000_000, "M")
    if n >= _K_THRESHOLD:
        return _with_suffix(n / 1_000, "K")
    return str(n)


def _with_suffix(value: float, suffix: str) -> str:
    text = f"{value:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return f"{text}{suffix}"