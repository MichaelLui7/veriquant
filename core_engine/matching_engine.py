"""Order matching model: slippage, transaction fees and daily price limits.

These are *market* parameters (external to the account invariants) — they shape
how much a trade costs and whether it can execute, while the verified ledger in
``risk_control`` guarantees the resulting account transitions stay sound.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MatchingConfig:
    slippage_bps: float = 1.0   # adverse fill, basis points
    fee_bps: float = 1.0        # transaction fee, basis points
    limit_pct: float = 0.0      # daily price limit (e.g. 0.10 = 10%); 0 = off


def trade_cost(notional: float, config: MatchingConfig) -> float:
    """Cash cost of trading `notional` (slippage + fee, in the same units)."""
    return notional * (config.slippage_bps + config.fee_bps) / 10000.0


def is_limit_locked(prev_price: float, price: float, config: MatchingConfig) -> bool:
    """True when the bar's move hit the daily price limit (no liquidity)."""
    if config.limit_pct <= 0.0 or prev_price <= 0.0:
        return False
    return abs(price / prev_price - 1.0) >= config.limit_pct
