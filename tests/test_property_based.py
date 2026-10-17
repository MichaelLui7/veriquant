"""Property-based fuzzing tests verifying Dafny invariants hold across random sequences."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hypothesis import given, settings, strategies as st
from risk_control.gateway import SCALE, VerifiedLedger, to_fixed


@settings(max_examples=200)
@given(
    initial_cash=st.floats(min_value=100.0, max_value=1e7, allow_nan=False, allow_infinity=False),
    ops=st.lists(
        st.tuples(
            st.sampled_from(["lock", "release", "fill", "sell", "cost"]),
            st.floats(min_value=0.01, max_value=5e6, allow_nan=False, allow_infinity=False),
        ),
        min_size=1,
        max_size=30,
    ),
)
def test_fuzz_verified_ledger_invariants(initial_cash: float, ops: list[tuple[str, float]]) -> None:
    """No matter what sequence of operations is thrown at VerifiedLedger,
    non-negativity, leverage ceiling (<= 2.0x), and fund conservation must hold."""
    ledger = VerifiedLedger(cash=initial_cash)

    for op, amount in ops:
        prev_equity_fixed = to_fixed(ledger.equity)
        if op == "lock":
            ledger.try_lock(amount)
            assert to_fixed(ledger.equity) == prev_equity_fixed
        elif op == "release":
            ledger.release(amount)
            assert to_fixed(ledger.equity) == prev_equity_fixed
        elif op == "fill":
            if ledger.account.locked_cash >= amount:
                ledger.fill(ledger.account.locked_cash, amount)
                assert to_fixed(ledger.equity) == prev_equity_fixed
        elif op == "sell":
            ledger.sell(amount)
            assert to_fixed(ledger.equity) == prev_equity_fixed
        elif op == "cost":
            ledger.pay_cost(amount)

        acc = ledger.account
        # 1. 余额永不为负
        assert acc.cash >= 0.0
        assert acc.locked_cash >= 0.0
        assert acc.position_value >= 0.0
        # 2. 杠杆率永不突破 2.0x (在定点数精度下严格成立)
        d_acc = acc.to_dafny()
        assert (d_acc.positionValue + d_acc.lockedCash) * SCALE <= (
            d_acc.cash + d_acc.lockedCash + d_acc.positionValue
        ) * 20000