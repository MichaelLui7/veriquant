// Stop-loss bound under a bounded-gap (slippage) assumption.
//
// In real markets a stop-loss cannot guarantee a loss below a fixed threshold,
// because of overnight gaps and illiquidity. The honest theorem is conditional:
// under the explicit precondition that consecutive prices jump by at most
// `maxGap`, the realised loss is bounded by the "ideal" stop loss plus
// maxGap * position. This `requires` clause is the essence of formal
// verification: we make the assumption explicit and prove the consequence.

include "Types.dfy"

module StopLossBounds {
  import Types

  // Per-unit loss bound (linear arithmetic; proved by the solver directly).
  lemma StopLossPerUnitBound(entryPrice: int, stopPrice: int, fillPrice: int, maxGap: int)
    requires entryPrice >= stopPrice
    requires fillPrice >= stopPrice - maxGap
    requires maxGap >= 0
    ensures entryPrice - fillPrice <= entryPrice - stopPrice + maxGap
  {
  }

  // Total loss bound for a long position of `position` units.
  lemma StopLossTotalBound(entryPrice: int, stopPrice: int, fillPrice: int,
                           position: int, maxGap: int)
    requires entryPrice >= stopPrice
    requires fillPrice >= stopPrice - maxGap
    requires position >= 0
    requires maxGap >= 0
    ensures (entryPrice - fillPrice) * position <=
            (entryPrice - stopPrice + maxGap) * position
  {
    StopLossPerUnitBound(entryPrice, stopPrice, fillPrice, maxGap);
  }
}
