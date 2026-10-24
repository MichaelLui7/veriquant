"""Verified portfolio ledger — runtime wiring into ``risk_control`` with Event Replay."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from core_engine.matching_engine import MatchingConfig, is_limit_locked, trade_cost
from risk_control.gateway import VerifiedLedger, to_fixed


@dataclass(frozen=True)
class LedgerEvent:
    """Deterministic logical event record for Event-Level Replay."""

    bar: int
    action: str          # "BUY", "SELL", "REJECT_LIMIT", "REJECT_RISK", "REJECT_COST"
    requested_delta: int # Fixed-point notional delta
    executed_cost: int   # Fixed-point fee + slippage
    cash_fp: int
    locked_fp: int
    pos_fp: int
    state_hash: str      # Cumulative SHA-256 canonical state hash H_t


class VerifiedPortfolio:
    """Value-based portfolio driven by the Dafny-verified ledger with atomic rollback."""

    def __init__(self, cash: float, matching: MatchingConfig | None = None,
                 max_leverage: float = 2.0, record_events: bool = False) -> None:
        self.ledger = VerifiedLedger(cash=cash, max_leverage=max_leverage)
        self.matching = matching or MatchingConfig()
        self.rejections = 0
        self.executed_trades = 0
        self.record_events = record_events
        self.events: list[LedgerEvent] = []
        self._rolling_hash = "0" * 64

    @property
    def account(self):
        return self.ledger.account

    @property
    def equity(self) -> float:
        return self.ledger.equity

    @property
    def state_hash(self) -> str:
        return self._rolling_hash

    def canonical_state_bytes(self, bar: int) -> bytes:
        d_acc = self.ledger.account.to_dafny()
        payload = (
            f"{bar}|{d_acc.cash}|{d_acc.lockedCash}|{d_acc.positionValue}"
            f"|{self.rejections}|{self.executed_trades}"
        )
        return payload.encode("ascii")

    def update_state_hash(self, bar: int) -> str:
        h = hashlib.sha256()
        h.update(self._rolling_hash.encode("ascii"))
        h.update(b"::")
        h.update(self.canonical_state_bytes(bar))
        self._rolling_hash = h.hexdigest()
        return self._rolling_hash

    def mark_to_market(self, price: float, prev_price: float) -> None:
        self.ledger.mark_to_market(price, prev_price)

    def rebalance(self, target_value: float, prev_price: float | None = None,
                  price: float | None = None, bar: int = 0) -> None:
        if prev_price is not None and price is not None and \
                is_limit_locked(prev_price, price, self.matching):
            self.rejections += 1
            self._log_event(bar, "REJECT_LIMIT", target_value - self.ledger.account.position_value, 0.0)
            return

        delta = target_value - self.ledger.account.position_value
        if abs(delta) < 1e-9:
            return
        if delta > 0:
            self._buy(delta, bar)
        else:
            self._sell(-delta, bar)

    def _log_event(self, bar: int, action: str, delta: float, cost: float) -> None:
        if not self.record_events:
            return
        d_acc = self.ledger.account.to_dafny()
        h = self.update_state_hash(bar)
        self.events.append(
            LedgerEvent(
                bar=bar,
                action=action,
                requested_delta=to_fixed(delta),
                executed_cost=to_fixed(cost),
                cash_fp=int(d_acc.cash),
                locked_fp=int(d_acc.lockedCash),
                pos_fp=int(d_acc.positionValue),
                state_hash=h,
            )
        )

    def _buy(self, notional: float, bar: int = 0) -> None:
        snapshot = self.ledger.account
        cost = trade_cost(notional, self.matching)

        if not self.ledger.try_lock(notional):
            self.rejections += 1
            self._log_event(bar, "REJECT_RISK", notional, 0.0)
            return

        self.ledger.fill(notional, notional)

        if cost > 0 and not self.ledger.pay_cost(cost):
            self.ledger.restore(snapshot)
            self.rejections += 1
            self._log_event(bar, "REJECT_COST", notional, cost)
            return

        self.executed_trades += 1
        self._log_event(bar, "BUY", notional, cost)

    def _sell(self, notional: float, bar: int = 0) -> None:
        snapshot = self.ledger.account
        cost = trade_cost(notional, self.matching)

        if not self.ledger.sell(notional):
            self.rejections += 1
            self._log_event(bar, "REJECT_RISK", -notional, 0.0)
            return

        if cost > 0 and not self.ledger.pay_cost(cost):
            self.ledger.restore(snapshot)
            self.rejections += 1
            self._log_event(bar, "REJECT_COST", -notional, cost)
            return

        self.executed_trades += 1
        self._log_event(bar, "SELL", -notional, cost)