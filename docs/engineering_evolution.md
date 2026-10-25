# 🔬 VeriQuant Architecture Evolution & Engineering Post-Mortem

> 🌐 **Language**: **English** | [简体中文 (zh-CN)](engineering_evolution.zh-CN.md)

This document records the architectural evolution of **VeriQuant** from an initial prototype (`v0.1`) to a hardened, formally-bounded distributed backtesting engine (`v0.2`), detailing **valuable engineering setbacks, peer/advisor audit findings, root-cause analyses, and Before/After code comparisons**.

---

## 1. Audit Motivation: Why "Passing CLI + Equal Sharpe" Is Not Enough

In `v0.1`, `test_distributed_consistency.py` confirmed that single-process and Ray workers produced identical Sharpe ratios. However, rigorous technical review revealed three critical verification gaps:

1. **Trusted Computing Base (TCB) Boundary Leaks**:
   Proving local ledger primitives in Dafny does not automatically guarantee end-to-end safety. If the Python portfolio bridge fails to roll back state when fee deduction fails, or fails to propagate user-configured leverage caps (e.g., `1.5x`) into the `2.0x` Dafny ceiling, formal guarantees are silently bypassed.
2. **Shared Logic Bugs Across Execution Modes**:
   Bit-for-bit equality between single-process and Ray workers only proves *determinism*, not *semantic correctness*. Both modes can identically execute the same bug (e.g., omitting $t=0$ initial capital or misaligning indicator warm-up windows).
3. **Three Orthogonal Dimensions of Distributed Correctness**:
   $$\text{System Correctness} \triangleq \text{Functional Correctness} \land \text{Partition Invariance} \land \text{Failure Recovery Correctness}$$
   We enforce a 4-layer verification hierarchy: **Numerical Consistency $\subset$ Event Consistency (`SHA-256` state hashes) $\subset$ Execution Completeness (`job_id` idempotency) $\subset$ Financial Semantic Correctness (Oracle & Prefix Invariance)**.

---

## 2. Valuable Engineering Setbacks & Lessons Learned

* **Setback 1 — Z3 Non-Linear Integer Arithmetic (NIA) Timeouts**:
  Initially, `maxLeverageBps` was a mutable field on `AccountState`. Chained transitions (`TryLock -> Fill -> Cancel`) turned `(cash + locked + pos) * maxLeverageBps` into `symbol * symbol`, causing Z3 to time out after 40s.
  *Fix*: Fixed `MAX_LEVERAGE_BPS := 20000` (2.0x) as a compile-time constant in Dafny (reducing obligations to fast Linear Integer Arithmetic, LIA), while enforcing stricter user-specified leverage bounds (`0 < L <= 2.0`) in `VerifiedLedger`.
* **Setback 2 — The 2.4x Vectorized Speedup Wall (Memory Bandwidth vs. CPU)**:
  Vectorized `numpy` scans (`run_single_backtest`) saturated memory bandwidth at ~2.4x across 8 cores, whereas the CPU-bound Dafny event-driven path (`run_verified_backtest`) achieved ~6.0x speedup. We enforced zero-copy read-only views (`prices.view().flags.writeable = False`) and task batching (`batch_size`) to amortize Ray RPC overhead.
* **Setback 3 — Compositional Invariant Violation in Cross-Sectional Sharding**:
  Even if Worker A (AAPL) and Worker B (NVDA) independently pass Dafny's `$80,000` check against a `$100,000` account, merging them requires `$160,000` ($\text{Valid}(A) \land \text{Valid}(B) \not\Rightarrow \text{Valid}(A \oplus B)$). Consequently, full worker parallelism is strictly restricted to **Parameter-Space Partitioning** with isolated accounts.

---

## 3. Core Defect Remediations: Before vs. After

### Remediation 1: Atomic Fee Rollback & User Leverage Propagation (Fixes #1)

* **Before (`v0.1` — Non-atomic fee deduction leaves unpaid position open)**:
  ```python
  # core_engine/portfolio.py (v0.1)
  def _buy(self, notional: float) -> None:
      if not self.ledger.try_lock(notional):
          self.rejections += 1
          return
      # BUG: Position is mutated here; if pay_cost fails below, fill is never rolled back!
      self.ledger.fill(notional, notional)
      cost = trade_cost(notional, self.matching)
      if cost > 0 and not self.ledger.pay_cost(cost):
          self.rejections += 1
  ```

* **After (`v0.2` — Immutable snapshot rollback & user `max_leverage` enforcement)**:
  ```python
  # core_engine/portfolio.py (v0.2)
  def _buy(self, notional: float, bar: int = 0) -> None:
      snapshot = self.ledger.account  # Save frozen dataclass snapshot
      cost = trade_cost(notional, self.matching)

      if not self.ledger.try_lock(notional):
          self.rejections += 1
          self._log_event(bar, "REJECT_RISK", notional, 0.0)
          return

      self.ledger.fill(notional, notional)

      if cost > 0 and not self.ledger.pay_cost(cost):
          self.ledger.restore(snapshot)  # Atomic rollback on fee failure
          self.rejections += 1
          self._log_event(bar, "REJECT_COST", notional, cost)
          return

      self.executed_trades += 1
      self._log_event(bar, "BUY", notional, cost)
  ```

---

### Remediation 2: Aligning $t=0$ Initial Equity, Warm-Up Windows & State Hashing

* **Before (`v0.1` — Omitted $t=0$ initial capital & counted raw signals instead of executed trades)**:
  ```python
  # core_engine/backtester.py (v0.1)
  equity = float(cfg["initial_capital"]) * np.cumprod(1.0 + net)  # Length N-1 (misses bar 0)
  m["num_trades"] = int(np.count_nonzero(np.diff(signals)))       # Ignores risk rejections
  ```

* **After (`v0.2` — Length-$N$ equity curve, common `warmup_bars`, and `SHA-256` state hash)**:
  ```python
  # core_engine/backtester.py (v0.2)
  init_cap = float(cfg["initial_capital"])
  equity = np.empty(prices.size, dtype=np.float64)
  equity[0] = init_cap
  equity[1:] = init_cap * np.cumprod(1.0 + net)

  eval_equity = equity[warmup:]
  m["num_trades"] = portfolio.executed_trades
  m["exposure"] = float(np.mean(actual_exposure[warmup:]))
  m["final_state_hash"] = portfolio.state_hash
  ```

---

### Remediation 3: Preventing `NaN/Inf` Pareto Poisoning & Enforcing `job_id` Completeness (Fixes #2)

* **Before (`v0.1` — `NaN` Sharpe bypasses `_dominates` because `NaN >= x` is `False`)**:
  ```python
  # distributed/aggregator.py (v0.1)
  def pareto_frontier(results: list[dict]) -> list[dict]:
      frontier: list[dict] = []
      for r in results:
          if any(_dominates(f, r) for f in frontier):
              continue
          frontier = [f for f in frontier if not _dominates(r, f)]
          frontier.append(r)
      return frontier
  ```

* **After (`v0.2` — Finite metric validation, deterministic tie-breaking & `job_id` deduplication)**:
  ```python
  # distributed/aggregator.py (v0.2)
  def is_valid_result(r: dict) -> bool:
      for k in REQUIRED_SCALAR_KEYS:
          val = r.get(k)
          if val is None or not isinstance(val, (int, float)) or not math.isfinite(val):
              return False
      return r["max_drawdown"] <= 1e-12
  ```