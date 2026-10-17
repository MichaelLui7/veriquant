// Fixed-point domain model.
//
// Convention: every monetary amount and price is represented as an integer
// scaled by SCALE (e.g. SCALE = 10000 means 1.0000 == 10000). Using fixed-point
// integers (instead of IEEE 754 floats) avoids precision loss and lets the SMT
// solver (Z3) decide integer arithmetic directly.
//
// The maximum leverage is a system-wide risk policy constant (not a per-account
// field). Keeping it constant makes the leverage invariant purely linear
// arithmetic (`equity * MAX_LEVERAGE_BPS`), which the solver decides instantly
// and deterministically. Per-account limits can be layered on top by scaling a
// per-account exposure cap.

module Types {
  // Scale factor for fixed-point arithmetic.
  const SCALE: int := 10000

  // Maximum allowed leverage, in basis points (20000 == 2.0x). System-wide
  // pre-trade risk policy enforced by the verified gateway.
  const MAX_LEVERAGE_BPS: int := 20000

  // Immutable snapshot of an account.
  datatype AccountState = AccountState(
    cash: int,          // available cash (fixed point)
    lockedCash: int,    // cash frozen by open orders (fixed point)
    positionValue: int  // current market value of holdings (fixed point)
  )

  // Order side.
  datatype Side = Buy | Sell

  // Order lifecycle states.
  datatype OrderState = Pending | PartiallyFilled | Filled | Cancelled

  // An order.
  datatype Order = Order(
    id: nat,
    side: Side,
    notional: int,   // total order notional
    locked: int,     // notional currently frozen
    state: OrderState
  )

  // True when the state may still be filled or cancelled.
  ghost predicate IsOpen(s: OrderState) {
    s == Pending || s == PartiallyFilled
  }

  // True when the state is terminal.
  ghost predicate IsTerminal(s: OrderState) {
    s == Filled || s == Cancelled
  }
}
