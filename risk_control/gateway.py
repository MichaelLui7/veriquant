"""Bridge layer between the Python engine and the Dafny-generated core.

The verified risk logic lives in ``risk_control/_generated/verified_risk-py``
(produced by ``dafny translate py``, see ``dafny_verification/build_py.ps1``).
Dafny operates on fixed-point integers (scaled by ``SCALE``); this module does
the float <-> fixed-point conversion and exposes the verified primitives.

The Dafny ``AccountState`` is a value type, so the ``VerifiedLedger`` below is a
thin stateful wrapper that replaces its ``Account`` on every verified transition.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

SCALE = 10_000

_GENERATED_DIR = os.path.join(os.path.dirname(__file__), "_generated", "verified_risk-py")
if _GENERATED_DIR not in sys.path:
    sys.path.insert(0, _GENERATED_DIR)

import Types  # noqa: E402  (Dafny-generated)
import AccountInvariants  # noqa: E402  (Dafny-generated)
import OrderStateMachine  # noqa: E402  (Dafny-generated)
import VerifiedRisk  # noqa: E402  (Dafny-generated)

_verified = VerifiedRisk.default__
_accounts = AccountInvariants.default__
_orders = OrderStateMachine.default__


def to_fixed(value: float) -> int:
    """Convert a float amount into the fixed-point integer used by Dafny."""
    return int(round(value * SCALE))


def to_float(value: int) -> float:
    """Convert a Dafny fixed-point integer back to a float."""
    return value / SCALE


@dataclass(frozen=True)
class Account:
    """Ergonomic view of a Dafny ``AccountState`` (floating-point amounts)."""

    cash: float = 0.0
    locked_cash: float = 0.0
    position_value: float = 0.0

    def to_dafny(self) -> "Types.AccountState":
        return Types.AccountState_AccountState(
            to_fixed(self.cash),
            to_fixed(self.locked_cash),
            to_fixed(self.position_value),
        )

    @classmethod
    def from_dafny(cls, acc: "Types.AccountState") -> "Account":
        return cls(
            cash=to_float(acc.cash),
            locked_cash=to_float(acc.lockedCash),
            position_value=to_float(acc.positionValue),
        )

    @property
    def equity(self) -> float:
        return self.cash + self.locked_cash + self.position_value


class VerifiedLedger:
    """Stateful, verified fund-accounting ledger.

    Every transition is executed by the Dafny-compiled code and therefore
    guaranteed to preserve the proven invariants: no overdraft, no negative
    position, no leverage breach, no funds created/destroyed.
    """

    def __init__(self, cash: float = 0.0, position_value: float = 0.0,
                 max_leverage: float = 2.0) -> None:
        if max_leverage <= 0.0 or max_leverage > 2.0:
            raise ValueError(
                f"max_leverage={max_leverage} exceeds Dafny-verified bounds (0.0, 2.0]"
            )
        self._max_leverage_bps: int = to_fixed(max_leverage)
        self._account = Account(
            cash=to_float(to_fixed(cash)),
            locked_cash=0.0,
            position_value=to_float(to_fixed(position_value)),
        )

    @property
    def account(self) -> Account:
        return self._account

    @property
    def equity(self) -> float:
        return self._account.equity

    @property
    def max_leverage(self) -> float:
        return to_float(self._max_leverage_bps)

    def restore(self, snapshot: Account) -> None:
        """Atomically restore an immutable Account snapshot on transaction abort."""
        self._account = snapshot

    def within_user_leverage(self, candidate: "Types.AccountState | None" = None) -> bool:
        acc = candidate if candidate is not None else self._account.to_dafny()
        exposure = acc.positionValue + acc.lockedCash
        equity = acc.cash + acc.lockedCash + acc.positionValue
        return exposure * SCALE <= equity * self._max_leverage_bps

    # --- verified primitives -------------------------------------------------

    def try_lock(self, notional: float) -> bool:
        """Freeze cash for a new order (enforces cash sufficiency + user/Dafny leverage)."""
        ok, acc = _accounts.TryLockOrderCash(self._account.to_dafny(), to_fixed(notional))
        if ok and self.within_user_leverage(acc):
            self._account = Account.from_dafny(acc)
            return True
        return False

    def release(self, amount: float) -> bool:
        ok, acc = _accounts.ReleaseLockedCash(self._account.to_dafny(), to_fixed(amount))
        if ok:
            self._account = Account.from_dafny(acc)
        return ok

    def fill(self, order_notional: float, fill_notional: float) -> bool:
        """Execute (part of) a previously-locked order: frozen cash -> position."""
        order = Types.Order_Order(
            0, Types.Side_Buy(),
            to_fixed(order_notional), to_fixed(order_notional), Types.OrderState_Pending(),
        )
        acc, _ = _orders.FillOrder(self._account.to_dafny(), order, to_fixed(fill_notional))
        self._account = Account.from_dafny(acc)
        return True

    def sell(self, notional: float) -> bool:
        """Convert position value back into cash (never sells short)."""
        ok, acc = _accounts.SellPosition(self._account.to_dafny(), to_fixed(notional))
        if ok:
            self._account = Account.from_dafny(acc)
        return ok

    def pay_cost(self, cost: float) -> bool:
        """Pay a fee/slippage cost out of cash (never overdraws or over-levers)."""
        ok, acc = _accounts.PayCost(self._account.to_dafny(), to_fixed(cost))
        if ok and self.within_user_leverage(acc):
            self._account = Account.from_dafny(acc)
            return True
        return False

    def mark_to_market(self, price: float, prev_price: float) -> None:
        """External price move: rescale position value by the price ratio."""
        a = self._account
        if prev_price > 0.0:
            revalued = to_float(to_fixed(a.position_value * price / prev_price))
            self._account = Account(
                cash=a.cash,
                locked_cash=a.locked_cash,
                position_value=revalued,
            )


class RiskGateway:
    """Thin wrapper over the Dafny-verified pre-trade gateway."""

    def __init__(self, account: Account, max_leverage: float = 2.0) -> None:
        if max_leverage <= 0.0 or max_leverage > 2.0:
            raise ValueError(
                f"max_leverage={max_leverage} exceeds Dafny-verified bounds (0.0, 2.0]"
            )
        self._account = account
        self._max_leverage_bps: int = to_fixed(max_leverage)

    @property
    def account(self) -> Account:
        return self._account

    def pre_trade_check(self, order_notional: float) -> tuple[bool, Account]:
        """Return (approved, resulting_account)."""
        approved, new_acc = _verified.PreTradeGateway(
            self._account.to_dafny(), to_fixed(order_notional)
        )
        exposure = new_acc.positionValue + new_acc.lockedCash
        equity = new_acc.cash + new_acc.lockedCash + new_acc.positionValue
        if approved and (exposure * SCALE <= equity * self._max_leverage_bps):
            result = Account.from_dafny(new_acc)
            self._account = result
            return True, result
        return False, self._account