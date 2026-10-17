"""Verified portfolio ledger — the runtime wiring into ``risk_control``.

Every balance-changing operation goes through the Dafny-compiled primitives in
``risk_control.gateway`` (freeze/fill/sell/pay-cost), so the proven invariants
(no overdraft, no short, no leverage breach, funds conserved) hold at runtime —
the proof is about the code that actually runs, not a re-implementation.
"""

from __future__ import annotations

from core_engine.matching_engine import MatchingConfig, is_limit_locked, trade_cost
from risk_control.gateway import VerifiedLedger


class VerifiedPortfolio:
    """Value-based portfolio driven by the verified ledger.

    ``rebalance`` moves the position toward a target *value* (fraction of net
    equity) using verified buys/sells. Slippage and fees are external costs paid
    out of cash via the verified ``pay_cost`` primitive.
    """

    def __init__(self, cash: float, matching: MatchingConfig | None = None) -> None:
        self.ledger = VerifiedLedger(cash=cash)
        self.matching = matching or MatchingConfig()
        self.rejections = 0   # trades the verified gateway (or a price limit) rejected

    @property
    def account(self):
        return self.ledger.account

    @property
    def equity(self) -> float:
        return self.ledger.equity

    def mark_to_market(self, price: float, prev_price: float) -> None:
        self.ledger.mark_to_market(price, prev_price)

    def rebalance(self, target_value: float, prev_price: float | None = None,
                  price: float | None = None) -> None:
        """Move toward ``target_value`` of exposure.

        A daily price limit (if configured) blocks execution: no liquidity at the
        limit price, so the rebalance is skipped for that bar.
        """
        if prev_price is not None and price is not None and \
                is_limit_locked(prev_price, price, self.matching):
            self.rejections += 1
            return

        delta = target_value - self.ledger.account.position_value
        if abs(delta) < 1e-9:
            return
        if delta > 0:
            self._buy(delta)
        else:
            self._sell(-delta)

    # --- internals -----------------------------------------------------------

    def _buy(self, notional: float) -> None:
        # Verified: freeze cash (rejects on insufficient cash / leverage breach).
        if not self.ledger.try_lock(notional):
            self.rejections += 1
            return
        # Verified: convert frozen cash into position.
        self.ledger.fill(notional, notional)
        # External cost (slippage + fee), paid via the verified pay-cost primitive.
        cost = trade_cost(notional, self.matching)
        if cost > 0 and not self.ledger.pay_cost(cost):
            self.rejections += 1

    def _sell(self, notional: float) -> None:
        # Verified: convert position back into cash (rejects on short).
        if not self.ledger.sell(notional):
            self.rejections += 1
            return
        cost = trade_cost(notional, self.matching)
        if cost > 0 and not self.ledger.pay_cost(cost):
            self.rejections += 1
