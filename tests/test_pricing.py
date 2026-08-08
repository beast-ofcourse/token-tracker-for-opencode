"""Tests for tracker.pricing (T-006 pricing and cost computation)."""

from tracker.config import Price
from tracker.pricing import compute_cost, format_tokens, price_for


class Session:
    """Minimal stand-in for a Session (tracker.store owns the real one).

    Carries the `provider/model` key plus the token buckets and the
    database-recorded cost that compute_cost reads.
    """

    def __init__(
        self,
        model_key: str,
        input: int = 0,
        output: int = 0,
        reasoning: int = 0,
        cache_read: int = 0,
        cache_write: int = 0,
        cost_db: float = 0.0,
    ):
        self.model_key = model_key
        self.tokens = {
            "input": input,
            "output": output,
            "reasoning": reasoning,
            "cache_read": cache_read,
            "cache_write": cache_write,
        }
        self.cost_db = cost_db


GPT4O = Price(input=2.50, output=10.00, cache_read=1.25, cache_write=2.50)


def test_free_model_costs_zero_and_is_not_unpriced():
    session = Session("opencode/deepseek-v4-flash-free", input=1_000_000, output=50_000)
    cost, unpriced = compute_cost(session, {})
    assert cost == 0.0
    assert unpriced is False


def test_explicit_price_wins_for_free_model():
    pricing = {"opencode/deepseek-v4-flash-free": Price(5.0, 6.0, 7.0, 8.0)}
    session = Session("opencode/deepseek-v4-flash-free", input=1_000_000)
    cost, unpriced = compute_cost(session, pricing)
    assert cost == 5.0
    assert unpriced is False


def test_paid_model_exact_cost_for_known_tokens():
    session = Session(
        "openai/gpt-4o",
        input=1_000_000,
        output=100_000,
        reasoning=0,
        cache_read=200_000,
        cache_write=50_000,
    )
    cost, unpriced = compute_cost(session, {"openai/gpt-4o": GPT4O})
    # (1M * 2.50 + 100K * 10.00 + 200K * 1.25 + 50K * 2.50) / 1M
    assert cost == 3.875
    assert unpriced is False


def test_million_input_tokens_cost_exactly_input_price():
    # Acceptance criterion: 1,000,000 input tokens on gpt-4o (input 2.50) -> 2.50.
    session = Session("openai/gpt-4o", input=1_000_000)
    cost, unpriced = compute_cost(session, {"openai/gpt-4o": GPT4O})
    assert cost == 2.50
    assert unpriced is False


def test_unknown_model_with_zero_db_cost():
    session = Session("unknown/vendor-model", input=1_000_000)
    cost, unpriced = compute_cost(session, {})
    assert cost == 0.0
    assert unpriced is True


def test_unknown_model_uses_db_cost():
    session = Session("unknown/vendor-model", input=1_000_000, cost_db=3.25)
    cost, unpriced = compute_cost(session, {})
    assert cost == 3.25
    assert unpriced is True


def test_reasoning_priced_as_input():
    session = Session("openai/gpt-4o", reasoning=1_000_000)
    cost, unpriced = compute_cost(session, {"openai/gpt-4o": GPT4O})
    assert cost == 2.50
    assert unpriced is False


def test_cache_buckets_priced_correctly():
    session = Session("openai/gpt-4o", cache_read=1_000_000, cache_write=1_000_000)
    cost, unpriced = compute_cost(session, {"openai/gpt-4o": GPT4O})
    assert cost == 1.25 + 2.50
    assert unpriced is False


def test_price_for_exact_match_wins_over_free_suffix():
    pricing = {"opencode/deepseek-v4-flash-free": Price(1.0, 2.0, 3.0, 4.0)}
    assert price_for("opencode/deepseek-v4-flash-free", pricing) == Price(1.0, 2.0, 3.0, 4.0)


def test_price_for_free_suffix_without_exact_match():
    assert price_for("opencode/deepseek-v4-flash-free", {}) == Price(0.0, 0.0, 0.0, 0.0)


def test_price_for_unknown_returns_none():
    assert price_for("openai/gpt-4o", {}) is None


def test_format_tokens():
    assert format_tokens(1_200_000) == "1.2M"
    assert format_tokens(585_000) == "585K"
    assert format_tokens(1234) == "1234"
    assert format_tokens(2_000_000) == "2M"
    assert format_tokens(12_345) == "12.3K"
    assert format_tokens(0) == "0"


def test_format_tokens_billions():
    assert format_tokens(1_500_000_000) == "1.5B"
    assert format_tokens(2_000_000_000) == "2B"
    assert format_tokens(999_000_000) == "999M"