// Top-level verified risk gateway.
//
// This is the single entry file compiled to Python (see build_py.sh). It
// re-exports the verified pre-trade gateway plus runtime test methods used by
// the Dafny test runner.
//
// StopLossBounds.dfy (the bounded-slippage theorems) is intentionally NOT
// imported here: those lemmas are pure specification (ghost) and their
// non-linear facts would pollute this module's SMT context. They are verified
// standalone by the build script.

include "Types.dfy"
include "AccountInvariants.dfy"
include "OrderStateMachine.dfy"

module VerifiedRisk {
  import Types
  import AccountInvariants
  import OrderStateMachine

  // Atomic pre-trade check: approve an order (and freeze its cash) or reject it
  // without touching the account. Delegates to the verified TryLockOrderCash.
  method PreTradeGateway(acc: Types.AccountState, orderNotional: int)
    returns (approved: bool, newAcc: Types.AccountState)
    requires AccountInvariants.ValidAccount(acc)
    requires orderNotional > 0
    ensures AccountInvariants.ValidAccount(newAcc)
    ensures !approved ==> newAcc == acc
    ensures AccountInvariants.TotalCash(newAcc) == AccountInvariants.TotalCash(acc)
  {
    var locked, acc2 := AccountInvariants.TryLockOrderCash(acc, orderNotional);
    if locked {
      newAcc := acc2;
      approved := true;
    } else {
      newAcc := acc;
      approved := false;
    }
  }

  // Complete lifecycle: lock cash for an order, fill it, then release the
  // remaining frozen cash. End-to-end conservation of net equity.
  method FullOrderLifecycle(acc: Types.AccountState, orderNotional: int, fillNotional: int)
    returns (finalAcc: Types.AccountState)
    requires AccountInvariants.ValidAccount(acc)
    requires orderNotional > 0
    requires 0 <= fillNotional <= orderNotional
    requires orderNotional <= acc.cash
    requires (acc.positionValue + acc.lockedCash + orderNotional) * Types.SCALE <=
             (acc.cash + acc.lockedCash + acc.positionValue) * Types.MAX_LEVERAGE_BPS
    ensures AccountInvariants.ValidAccount(finalAcc)
    ensures AccountInvariants.NetEquity(finalAcc) == AccountInvariants.NetEquity(acc)
  {
    var ok, locked := AccountInvariants.TryLockOrderCash(acc, orderNotional);
    assert ok;
    var order := Types.Order(1, Types.Buy, orderNotional, orderNotional, Types.Pending);
    var acc2, filledOrder := OrderStateMachine.FillOrder(locked, order, fillNotional);
    var ok2, acc3 := AccountInvariants.ReleaseLockedCash(acc2, filledOrder.locked);
    finalAcc := acc3;
  }

  method {:test} {:vcs_split_on_every_assert} TestLockAndRelease()
  {
    var acc := Types.AccountState(100000, 0, 0);
    var ok, acc2 := AccountInvariants.TryLockOrderCash(acc, 30000);
    expect ok;
    expect acc2.lockedCash == 30000;
    expect acc2.cash == 70000;
    expect AccountInvariants.TotalCash(acc2) == AccountInvariants.TotalCash(acc);
    var ok2, acc3 := AccountInvariants.ReleaseLockedCash(acc2, 30000);
    expect ok2;
    expect acc3 == acc;
  }

  method {:test} {:vcs_split_on_every_assert} TestLeverageRejection()
  {
    var acc := Types.AccountState(100000, 0, 0);
    var ok, acc2 := AccountInvariants.TryLockOrderCash(acc, 300000);
    expect !ok;
    expect acc2 == acc;
  }

  method {:test} {:vcs_split_on_every_assert} TestOrderFillAndCancel()
  {
    var acc := Types.AccountState(100000, 0, 0);
    var ok, locked := AccountInvariants.TryLockOrderCash(acc, 30000);
    expect ok;
    var order := Types.Order(1, Types.Buy, 30000, 30000, Types.Pending);
    var a1, filled := OrderStateMachine.FillOrder(locked, order, 10000);
    expect filled.state == Types.PartiallyFilled;
    expect filled.locked == 20000;
    expect a1.lockedCash == 20000;
    expect a1.positionValue == 10000;
    var a2, cancelled := OrderStateMachine.CancelOrder(a1, filled);
    expect cancelled.state == Types.Cancelled;
    expect cancelled.locked == 0;
    expect a2.lockedCash == 0;
    expect a2.cash == 90000;
  }
}
