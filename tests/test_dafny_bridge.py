"""Consistency checks: Python <-> Dafny-generated verified core.

Verifies that the float/fixed-point bridge correctly drives the Dafny-compiled
risk gateway, and that the verified behavior matches the proven invariants
(no overdraft, no leverage breach, funds conserved, order lifecycle).
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from risk_control.gateway import Account, RiskGateway, SCALE, to_fixed  # noqa: E402


def test_approved_order_freezes_cash():
    gw = RiskGateway(Account(cash=10.0))
    approved, acc = gw.pre_trade_check(3.0)
    assert approved is True
    assert acc.cash == 7.0
    assert acc.locked_cash == 3.0


def test_leverage_rejection_leaves_account_untouched():
    # cash=10.0 at 2x leverage => max exposure 20.0; a 30.0 notional is rejected.
    gw = RiskGateway(Account(cash=10.0))
    approved, acc = gw.pre_trade_check(30.0)
    assert approved is False
    assert acc == Account(cash=10.0)


def test_fixed_point_roundtrip():
    assert to_fixed(1.2345) == 12345
    assert to_fixed(0.0001) == 1
    assert to_fixed(0.0) == 0


def test_full_order_lifecycle_via_dafny():
    # Directly drive the compiled Dafny module to assert the lifecycle and the
    # conservation invariants end-to-end.
    gen = os.path.join(PROJECT_ROOT, "risk_control", "_generated", "verified_risk-py")
    sys.path.insert(0, gen)
    import Types
    import AccountInvariants
    import OrderStateMachine

    acc = Types.AccountState_AccountState(100000, 0, 0)
    ok, locked = AccountInvariants.default__.TryLockOrderCash(acc, 30000)
    assert ok
    order = Types.Order_Order(1, Types.Side_Buy(), 30000, 30000, Types.OrderState_Pending())
    a1, filled = OrderStateMachine.default__.FillOrder(locked, order, 10000)
    assert filled.locked == 20000
    assert a1.lockedCash == 20000
    assert a1.positionValue == 10000
    a2, cancelled = OrderStateMachine.default__.CancelOrder(a1, filled)
    assert cancelled.locked == 0
    assert a2.cash == 90000
    assert a2.lockedCash == 0


if __name__ == "__main__":
    test_approved_order_freezes_cash()
    test_leverage_rejection_leaves_account_untouched()
    test_fixed_point_roundtrip()
    test_full_order_lifecycle_via_dafny()
    print("All bridge tests passed.")
