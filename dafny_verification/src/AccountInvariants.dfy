// Account invariants: conservation of funds and leverage limits.
//
// Proves, on every state transition of the account:
//   1. Conservation of funds (no double spend, no overdraft, no funds created
//      or destroyed): cash, locked cash and position value are never negative,
//      and the transition moves value between them without changing net equity.
//   2. Leverage ceiling: total exposure never exceeds net equity * max leverage.
//
// Because MAX_LEVERAGE_BPS is a constant, the leverage check is linear integer
// arithmetic, so the solver verifies these contracts instantly.

include "Types.dfy"

module AccountInvariants {
  import Types

  // A legal account state.
  ghost predicate ValidAccount(acc: Types.AccountState) {
    acc.cash >= 0 &&
    acc.lockedCash >= 0 &&
    acc.positionValue >= 0 &&
    // total exposure <= net equity * max leverage (in basis points)
    (acc.positionValue + acc.lockedCash) * Types.SCALE <=
      (acc.cash + acc.lockedCash + acc.positionValue) * Types.MAX_LEVERAGE_BPS
  }

  // Liquid cash: available + frozen. Conserved by lock and release operations.
  function TotalCash(acc: Types.AccountState): int {
    acc.cash + acc.lockedCash
  }

  // Total equity: cash + frozen + position value. Conserved by every internal
  // transition (lock, release, fill). Only external deposits/withdrawals and
  // mark-to-market changes alter it.
  function NetEquity(acc: Types.AccountState): int {
    acc.cash + acc.lockedCash + acc.positionValue
  }

  // Freeze cash for a new order. Never overdrafts, never violates the leverage
  // ceiling, and preserves both TotalCash and NetEquity.
  method TryLockOrderCash(acc: Types.AccountState, orderNotional: int)
    returns (success: bool, newAcc: Types.AccountState)
    requires ValidAccount(acc)
    requires orderNotional > 0
    ensures ValidAccount(newAcc)
    ensures success ==>
      (newAcc.cash == acc.cash - orderNotional &&
       newAcc.lockedCash == acc.lockedCash + orderNotional &&
       newAcc.positionValue == acc.positionValue)
    ensures !success ==> newAcc == acc
    ensures success ==
      (orderNotional <= acc.cash &&
       (acc.positionValue + acc.lockedCash + orderNotional) * Types.SCALE <=
         (acc.cash + acc.lockedCash + acc.positionValue) * Types.MAX_LEVERAGE_BPS)
    ensures TotalCash(newAcc) == TotalCash(acc)
    ensures NetEquity(newAcc) == NetEquity(acc)
  {
    if orderNotional <= acc.cash &&
       (acc.positionValue + acc.lockedCash + orderNotional) * Types.SCALE <=
         (acc.cash + acc.lockedCash + acc.positionValue) * Types.MAX_LEVERAGE_BPS
    {
      newAcc := Types.AccountState(acc.cash - orderNotional,
                                   acc.lockedCash + orderNotional,
                                   acc.positionValue);
      success := true;
    } else {
      newAcc := acc;
      success := false;
    }
  }

  // Unfreeze cash (after a fill or cancel). Only releases what is actually
  // frozen, and preserves both TotalCash and NetEquity.
  method ReleaseLockedCash(acc: Types.AccountState, release: int)
    returns (success: bool, newAcc: Types.AccountState)
    requires ValidAccount(acc)
    requires release >= 0
    ensures ValidAccount(newAcc)
    ensures success ==>
      (newAcc.lockedCash == acc.lockedCash - release &&
       newAcc.cash == acc.cash + release &&
       newAcc.positionValue == acc.positionValue)
    ensures !success ==> newAcc == acc
    ensures success == (release <= acc.lockedCash)
    ensures TotalCash(newAcc) == TotalCash(acc)
    ensures NetEquity(newAcc) == NetEquity(acc)
  {
    if release <= acc.lockedCash {
      newAcc := Types.AccountState(acc.cash + release,
                                   acc.lockedCash - release,
                                   acc.positionValue);
      success := true;
    } else {
      newAcc := acc;
      success := false;
    }
  }

  // Sell (part of) the position: convert position value back into available
  // cash. Never goes short (cannot sell more than held) and preserves net
  // equity; reducing exposure can only ease the leverage constraint.
  method SellPosition(acc: Types.AccountState, sellNotional: int)
    returns (success: bool, newAcc: Types.AccountState)
    requires ValidAccount(acc)
    requires sellNotional >= 0
    ensures ValidAccount(newAcc)
    ensures success ==>
      (newAcc.positionValue == acc.positionValue - sellNotional &&
       newAcc.cash == acc.cash + sellNotional &&
       newAcc.lockedCash == acc.lockedCash)
    ensures !success ==> newAcc == acc
    ensures success == (sellNotional <= acc.positionValue)
    ensures NetEquity(newAcc) == NetEquity(acc)
  {
    if sellNotional <= acc.positionValue {
      newAcc := Types.AccountState(acc.cash + sellNotional,
                                   acc.lockedCash,
                                   acc.positionValue - sellNotional);
      success := true;
    } else {
      newAcc := acc;
      success := false;
    }
  }

  // Pay a fee / slippage cost out of available cash. This is a real external
  // cost (it reduces net equity), so it is only allowed if it neither overdraws
  // the account nor pushes the account past the leverage ceiling.
  method PayCost(acc: Types.AccountState, cost: int)
    returns (success: bool, newAcc: Types.AccountState)
    requires ValidAccount(acc)
    requires cost >= 0
    ensures ValidAccount(newAcc)
    ensures success ==>
      (newAcc.cash == acc.cash - cost &&
       newAcc.lockedCash == acc.lockedCash &&
       newAcc.positionValue == acc.positionValue)
    ensures !success ==> newAcc == acc
    ensures success ==
      (cost <= acc.cash &&
       (acc.positionValue + acc.lockedCash) * Types.SCALE <=
         (acc.cash - cost + acc.lockedCash + acc.positionValue) * Types.MAX_LEVERAGE_BPS)
  {
    if cost <= acc.cash &&
       (acc.positionValue + acc.lockedCash) * Types.SCALE <=
         (acc.cash - cost + acc.lockedCash + acc.positionValue) * Types.MAX_LEVERAGE_BPS
    {
      newAcc := Types.AccountState(acc.cash - cost, acc.lockedCash, acc.positionValue);
      success := true;
    } else {
      newAcc := acc;
      success := false;
    }
  }
}
