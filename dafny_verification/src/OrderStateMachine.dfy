// Order state machine: safe state transitions and anti-double-spend.
//
// Proves:
//   1. Transitions only move toward terminal states (monotonic lifecycle).
//   2. Filling converts frozen cash into position value with net equity
//      preserved (no funds created or destroyed).
//   3. Cancelling releases exactly the remaining frozen cash and cannot happen
//      twice (terminal states have no outgoing transitions).

include "Types.dfy"
include "AccountInvariants.dfy"

module OrderStateMachine {
  import Types
  import AccountInvariants

  // A legal transition: only forward progress toward a terminal state.
  ghost predicate ValidTransition(from: Types.OrderState, to: Types.OrderState) {
    match from
    case Pending => to == Types.PartiallyFilled || to == Types.Filled || to == Types.Cancelled
    case PartiallyFilled => to == Types.PartiallyFilled || to == Types.Filled || to == Types.Cancelled
    case Filled => false
    case Cancelled => false
  }

  // Terminal states have no outgoing transition (termination of the lifecycle).
  lemma TerminalStaysTerminal(s: Types.OrderState)
    requires Types.IsTerminal(s)
    ensures forall t :: !ValidTransition(s, t)
  {
    match s
    case Filled =>
    case Cancelled =>
    case Pending =>
    case PartiallyFilled =>
  }

  // Fill (part of) an open order: frozen cash is converted into position value.
  // Net equity is preserved, so ValidAccount still holds after the fill.
  method FillOrder(acc: Types.AccountState, o: Types.Order, fillNotional: int)
    returns (newAcc: Types.AccountState, newOrder: Types.Order)
    requires AccountInvariants.ValidAccount(acc)
    requires Types.IsOpen(o.state)
    requires fillNotional >= 0
    requires fillNotional <= o.locked
    requires o.locked <= acc.lockedCash
    ensures AccountInvariants.ValidAccount(newAcc)
    ensures newOrder.state == Types.Filled || newOrder.state == Types.PartiallyFilled
    ensures newOrder.state == Types.Filled ==> fillNotional == o.locked
    ensures ValidTransition(o.state, newOrder.state)
    ensures newOrder.locked == o.locked - fillNotional
    ensures newAcc.cash == acc.cash
    ensures newAcc.lockedCash == acc.lockedCash - fillNotional
    ensures newAcc.positionValue == acc.positionValue + fillNotional
    ensures AccountInvariants.NetEquity(newAcc) == AccountInvariants.NetEquity(acc)
  {
    var st := if fillNotional == o.locked then Types.Filled else Types.PartiallyFilled;
    newOrder := Types.Order(o.id, o.side, o.notional, o.locked - fillNotional, st);
    newAcc := Types.AccountState(acc.cash,
                                 acc.lockedCash - fillNotional,
                                 acc.positionValue + fillNotional);
  }

  // Cancel an open order: release exactly the remaining frozen cash. The order
  // becomes Cancelled (terminal), so its cash can never be released twice.
  method CancelOrder(acc: Types.AccountState, o: Types.Order)
    returns (newAcc: Types.AccountState, newOrder: Types.Order)
    requires AccountInvariants.ValidAccount(acc)
    requires Types.IsOpen(o.state)
    requires o.locked >= 0
    requires o.locked <= acc.lockedCash
    ensures AccountInvariants.ValidAccount(newAcc)
    ensures newOrder.state == Types.Cancelled
    ensures ValidTransition(o.state, newOrder.state)
    ensures newOrder.locked == 0
    ensures newAcc.positionValue == acc.positionValue
    ensures newAcc.lockedCash == acc.lockedCash - o.locked
    ensures newAcc.cash == acc.cash + o.locked
    ensures AccountInvariants.TotalCash(newAcc) == AccountInvariants.TotalCash(acc)
  {
    newOrder := Types.Order(o.id, o.side, o.notional, 0, Types.Cancelled);
    newAcc := Types.AccountState(acc.cash + o.locked,
                                 acc.lockedCash - o.locked,
                                 acc.positionValue);
  }
}
