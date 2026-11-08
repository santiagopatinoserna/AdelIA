"""List prices of the models the product calls, to turn usage_counters into dollars.

The table is usage_prices.json, beside this file: read by hand on 2026-11-08
from each provider's own pricing page, in USD, standard tier (no batch, no
priority, no regional surcharge), each row with the line it was read from.
Data and not code because a price table has to name model ids, and model ids
live in config.py and nowhere else in the logic (tests/test_model_config.py).

The figures are an ESTIMATE of the bill, not the bill: the invoice is what
counts, and these numbers age. When a price changes, change the JSON with the
date it was read. Keyed by the model name the code sends (the settings value,
an alias such as `mistral-small-latest` included), because that is what
usage_counters holds. A model with no official price sits in `unpriced` with
the reason, and its calls are reported apart instead of being priced at a
guess.

Prices live outside the table, as 6773d0b decided: they change, differ by
contract, and the counters must stay true when they do.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

_TABLE = json.loads((Path(__file__).with_name("usage_prices.json")).read_text(encoding="utf-8"))

READ_ON = date.fromisoformat(_TABLE["read_on"])
ANTHROPIC_PRICING = _TABLE["sources"]["anthropic"]
MISTRAL_PRICING = _TABLE["sources"]["mistral"]
OPENAI_PRICING = _TABLE["sources"]["openai"]


@dataclass(frozen=True)
class Price:
    """USD per million tokens, per page and per audio minute."""
    source: str
    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0  # the 5-minute write; the product sets no 1-hour cache
    per_page: float = 0.0
    per_audio_minute: float = 0.0
    quote: str = ""
    note: str = ""


_FIELDS = ("input", "output", "cache_read", "cache_write", "per_page", "per_audio_minute",
           "quote", "note")

PRICES: dict[tuple[str, str], Price] = {
    (row["provider"], row["model"]): Price(
        _TABLE["sources"][row["provider"]], **{k: row[k] for k in _FIELDS if k in row}
    )
    for row in _TABLE["prices"]
}

UNPRICED: dict[tuple[str, str], str] = {
    (row["provider"], row["model"]): row["reason"] for row in _TABLE["unpriced"]
}


def price_for(provider: str, model: str) -> Price | None:
    return PRICES.get((provider, model))


def estimate_usd(provider: str, model: str, counts: Mapping[str, Any]) -> float | None:
    """The list-price cost of `counts` on (provider, model), or None if unpriced."""
    price = price_for(provider, model)
    if price is None:
        return None

    def n(name: str) -> float:
        return float(counts.get(name) or 0)

    usd = (
        n("input_tokens") * price.input
        + n("output_tokens") * price.output
        + n("cache_read_tokens") * price.cache_read
        + n("cache_write_tokens") * price.cache_write
    ) / 1_000_000
    usd += n("pages") * price.per_page + n("audio_seconds") / 60 * price.per_audio_minute
    return round(usd, 6)


def unpriced_reason(provider: str, model: str) -> str:
    return UNPRICED.get((provider, model), "no official price recorded in usage_prices.json")
