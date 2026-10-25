# 🔬 VeriQuant 架构演进、踩坑挫折与深度审计复盘录 (Engineering Evolution & Post-Mortem)

> 🌐 **语言切换**: [English](engineering_evolution.md) | **简体中文 (zh-CN)**

本文档完整记录了 **VeriQuant** 在开发、跨平台构建、SMT 定理证明、以及历经两轮严苛同行评议（Advisor & Peer Review）过程中的**真实挫折、设计取舍、发现的隐蔽缺陷（P0/P1），以及改进前后的代码对比（Before vs. After）**。

---

## 一、 核心认知的跃迁：从“跑通 Happy-Path”到“严苛边界自证”

在项目初期（v0.1），我们跑通了 `Dafny -> Python` 编译链路、Ray 多核参数扫描和 CLI 交互，并通过了基础的 `Single-Process == Ray` 数值相等测试[cite: 1, 2]。然而，在随后的自我审视与 Advisor/同行审查中，我们直面了三个直击灵魂的工程追问：

1. **两次 CLI 演示成功 + 最终 Sharpe 数值相等，能证明系统达到生产级可靠性吗？**
   **不能。** 如果单进程与分布式 Worker 调用了同一个存在偏差的回测函数（如首日净值漏算、未来函数或预热期未对齐），两者会“100% 比特级一致地输出错误结果”。
2. **Dafny 证明了局部账本原语，等于证明了整个量化系统安全吗？**
   **不等于。** 形式化验证有其明确的**受信任计算基（Trusted Computing Base, TCB）**。如果 Python 桥接层在扣费失败时不回滚状态、或者用户在 CLI 设定的 `1.5x` 杠杆没有传进 Dafny 的 `2.0x` 常量网关，验证边界就会在运行时被静默穿透。
3. **分布式回测的完备正确性应该如何形式化定义？**
   我们将系统的全局正确性重新定义为三个正交维度的合取：
   $$\text{System Correctness} \triangleq \text{Functional Correctness} \land \text{Partition Invariance} \land \text{Failure Recovery Correctness}$$
   分别对应：**四层验证体系（数值一致性 $\subset$ 事件一致性 $\subset$ 执行完整性 $\subset$ 金融语义正确性）**。

---

## 二、 研发过程中的五大真实挫折与排障实录 (Valuable Setbacks)

### 挫折 1：与 Z3 非线性整数算术（NIA）的三天拉锯战
* **现象**：初版将最大允许杠杆 `maxLeverageBps` 设计为 `AccountState` 的可变字段[cite: 1]。`AccountInvariants.dfy` 单独验证秒过，但在验证包含“锁仓 $\to$ 部分成交 $\to$ 撤单”三次链式调用的 `TestOrderFillAndCancel` 时，Z3 求解器每次都在 40 秒后彻底超时（Timed out）[cite: 1]。
* **踩坑试错**：
  1. 起初怀疑是 `StopLossBounds.dfy` 中的非线性乘法污染了上下文，将其移出后依然超时[cite: 1]；
  2. 尝试用 `{:opaque}` 隐藏乘积项，虽消除了超时，但导致具体数值的前置条件无法展开证明[cite: 1]；
  3. 尝试开启 `--disable-nonlinear-arithmetic` 实验性标志，虽能通过但直接废掉了需要真非线性算术的止损定理[cite: 1]。
* **根因与顿悟**：链式调用后，新账户的 `maxLeverageBps` 在 SMT 上下文中退化为只通过 `ensures` 关联的符号变量，使得 `(cash + locked + pos) * maxLeverageBps` 变成了**符号变量 $\times$ 符号变量**，触发了 Z3 不完备且极不稳定的 NIA（非线性整数算术）启发式搜索[cite: 1]！
* **最终方案**：将系统级杠杆硬顶定义为编译期常量 `const MAX_LEVERAGE_BPS := 20000`（退化为纯线性整数算术 LIA，Z3 秒级判定）[cite: 1]，同时将更严格的**用户级动态杠杆（如 `1.5x`）下沉至 `VerifiedLedger` 桥接层做二次收紧校验**，并将真非线性的 `StopLossBounds.dfy` 独立模块验证[cite: 1]。

### 挫折 2：向量化回测仅 2.4x 加速比的困惑——内存带宽墙 (Memory Wall)
* **现象**：在 8 核 CPU 上运行 Ray 分布式网格搜索时，`run_single_backtest` 的实测加速比停留在 **2.4x** 左右，远低于理想线性加速[cite: 1]。
* **根因分析**：通过剖析任务特征发现，纯向量化回测（`np.diff` / `np.cumprod`）单次仅耗时数毫秒，且属于典型的 **Memory-Bound（内存带宽受限）** 操作[cite: 1]。单核运行时 NumPy 已接近榨干内存控制器带宽，8 个进程并发只会争抢 L3 缓存与内存总线；同时过细的任务粒度放大了 Ray 的 RPC 调度开销[cite: 1]。
* **最终方案**：
  1. 使用 `ray.put()` 将行情数组放入 Plasma Object Store，并在 Worker 端强制 `prices.view().flags.writeable = False` 实现零拷贝只读共享[cite: 1]；
  2. 在 `DistributedBacktestEngine` 中引入 `batch_size` 批量任务分片以摊销调度开销；
  3. 明确区分 **Memory-Bound（向量化粗筛，~2.4x）** 与 **CPU-Bound（`run_verified_backtest` 逐 Bar 状态机 + Dafny 原语校验 + SHA-256 哈希，实测可达 ~6.0x 近线性加速）** 的适用边界。

### 挫折 3：为什么拒绝“按时间切片（Time-Sharding）”与“盲目按标的切分（Cross-Sectional）”？
* **时间切片陷阱**：早期曾考虑将长周期历史数据按年份切分给不同 Worker。但量化策略具有强路径依赖性（$S_{t+1} = f(S_t, D_t, \theta)$）：均线依赖历史预热窗口（Warm-up），后一年的初始持仓与可用资金严格取决于前一年的交易结果，按时间切片会直接破坏复利净值与最大回撤的连续性，甚至引入未来函数[cite: 1]。
* **截面标的切分的组合语义陷阱（Advisor 核心拷问）**：
  假设账户总资金为 `$100,000`，若 Worker A（分析 AAPL）与 Worker B（分析 NVDA）各自读取初始 `$100,000` 并独立通过 `$80,000` 的 Dafny 局部风控检查，合并后将产生 `$160,000` 的总资金需求！这证明了**局部状态满足形式化不变式，并不自动保证合并后的全局投资组合满足不变式（$\text{Valid}(A) \land \text{Valid}(B) \not\Rightarrow \text{Valid}(A \oplus B)$）**。
* **架构准则**：VeriQuant 明确规定，无协调器的完全并行 Worker 仅用于**独立账户的参数空间分片（Parameter-Space Partitioning）**；若为共享同一资金池的多资产组合回测，Worker 仅可并行计算信号，资金分配与订单确认必须由确定性排序的中央执行器串行处理。

### 挫折 4：Dafny 编译产物泄露本机绝对路径与 `.gitignore` 的两难
* **现象**：最初将 `risk_control/_generated/` 加入 `.gitignore`，但会导致未安装 Dafny 编译器的审阅者克隆仓库后直接报 `ModuleNotFoundError: No module named 'Types'`[cite: 1, 2]。而当把 `_generated/` 提交进仓库时，又发现生成的 `VerifiedRisk.py` 内部嵌有本机绝对路径 `D:\Code\Project\veriquant\...`（因 PowerShell 脚本使用了 `$_.FullName`）[cite: 1, 2]。
* **其他跨平台与依赖暗坑**：
  * **CI Action 命名陷阱**：GitHub Actions 中误用 `dafny-lang/setup-dafny@v1` 会报 404，排查后修正为 `dafny-lang/setup-dafny-action@v1`；
  * **MCP 2.x 静默失效陷阱**：`mcp>=1.0` 默认升级到 `2.x` 后 `FastMCP` 被重命名为 `MCPServer`，被 `try/except` 捕获后静默失效，通过锁定 `mcp>=1.0,<2.0` 解决；
  * **Windows 控制台 GBK 崩溃**：Windows PowerShell 默认 GBK 编码在打印 `🛡️` 等字符时抛出 `UnicodeEncodeError`，通过在 CLI 入口配置 `sys.stdout.reconfigure(encoding="utf-8")` 根治。

---

## 三、 核心代码缺陷修复与演进对比 (Before vs. After)

### 演进 1：修补形式化验证边界——“买入+扣费”原子事务与用户杠杆下沉 (Fixes #1)

* **问题根因**：
  1. 在初版 `core_engine/portfolio.py` 的 `_buy()` 中，`self.ledger.fill()` 先将冻结现金转为持仓，随后才调用 `self.ledger.pay_cost(cost)` 扣减手续费与滑点[cite: 1]。当满仓买入（如 `$1,000` 现金买 `$1,000` 标的）时，`fill` 耗尽了全部现金，导致 `pay_cost` 失败返回 `False`；此时代码仅记录 `self.rejections += 1`，**却未回滚已成交的 `$1,000` 持仓**，造成“未付手续费却成功建仓”的状态分裂[cite: 1]！
  2. 用户在 CLI 指定的低杠杆限制（如 `1.5x`）未传入 `VerifiedLedger`，导致验证路径只检查 Dafny 的 `2.0x` 硬编码常量[cite: 1]。

* **改进前代码 (Before)**：
  ```python
  # core_engine/portfolio.py (v0.1 - 存在非原子扣费与忽略用户杠杆问题)
  def _buy(self, notional: float) -> None:
      if not self.ledger.try_lock(notional):
          self.rejections += 1
          return
      # 致命缺陷：此处已修改账本持仓，若下方 pay_cost 因余额不足失败，持仓不会回滚！
      self.ledger.fill(notional, notional)
      cost = trade_cost(notional, self.matching)
      if cost > 0 and not self.ledger.pay_cost(cost):
          self.rejections += 1
  ```

* **改进后代码 (After)**：
  ```python
  # core_engine/portfolio.py (v0.2 - 引入不可变快照原子回滚与用户级 max_leverage 校验)
  def _buy(self, notional: float, bar: int = 0) -> None:
      snapshot = self.ledger.account  # 保存 frozen dataclass 不可变账户快照
      cost = trade_cost(notional, self.matching)

      # Step 1: 同时校验 Dafny 2.0x 硬顶与用户配置的 max_leverage (如 1.5x)
      if not self.ledger.try_lock(notional):
          self.rejections += 1
          self._log_event(bar, "REJECT_RISK", notional, 0.0)
          return

      # Step 2: 冻结资金转持仓
      self.ledger.fill(notional, notional)

      # Step 3: 扣除外部滑点与手续费；若余额不足或扣费后突破杠杆，立即原子回滚至 snapshot！
      if cost > 0 and not self.ledger.pay_cost(cost):
          self.ledger.restore(snapshot)
          self.rejections += 1
          self._log_event(bar, "REJECT_COST", notional, cost)
          return

      self.executed_trades += 1
      self._log_event(bar, "BUY", notional, cost)
  ```

---

### 演进 2：修复向量化回测 $t=0$ 净值缺失、预热期对齐与真实成交统计

* **问题根因**：
  1. 初版 `run_single_backtest` 计算的 `equity` 数组长度为 $N-1$（丢失了 $t=0$ 的初始本金 `initial_capital`），导致 `metrics.total_return(equity)` 计算 `equity[-1] / equity[0] - 1` 时漏算了第 1 个交易日的盈亏与建仓成本[cite: 1]！而因为单进程和 Ray Worker 调用同一个函数，简单的 `Single == Ray` 测试完全无法发现该逻辑错误[cite: 1]。
  2. 初版 `run_verified_backtest` 统计 `num_trades` 和 `exposure` 时直接读取了策略意图 `signals`，即使所有订单被风控网关或涨跌停拦截，依然虚报交易次数[cite: 1]。
  3. 不同均线参数（如 `MA(5,20)` vs `MA(20,120)`）的指标预热期不同，未对齐评价区间会导致长周期策略少跑行情[cite: 1]。

* **改进前代码 (Before)**：
  ```python
  # core_engine/backtester.py (v0.1)
  # 缺陷 A：equity 长度为 N-1，丢失 t=0 初始本金
  equity = float(cfg["initial_capital"]) * np.cumprod(1.0 + net)

  # 缺陷 B：run_verified_backtest 按原始信号统计，无视风控拒单
  m["num_trades"] = int(np.count_nonzero(np.diff(signals)))
  m["exposure"] = float(np.mean(signals))
  ```

* **改进后代码 (After)**：
  ```python
  # core_engine/backtester.py (v0.2 - 对齐 t=0 净值、支持 warmup_bars、统计真实成交与 SHA-256 哈希)
  init_cap = float(cfg["initial_capital"])
  equity = np.empty(prices.size, dtype=np.float64)
  equity[0] = init_cap
  equity[1:] = init_cap * np.cumprod(1.0 + net)

  # 统一截取 [warmup_bars, N) 评价窗口，并通过 Independent Oracle 差分测试验证
  eval_equity = equity[warmup:]
  m["num_trades"] = portfolio.executed_trades
  m["exposure"] = float(np.mean(actual_exposure[warmup:]))
  m["final_state_hash"] = portfolio.state_hash
  ```

---

### 演进 3：拦截 `NaN / Inf` 污染帕累托前沿 & 强制 `job_id` 幂等完整性 (Fixes #2)

* **问题根因**：
  在 IEEE-754 浮点数规范下，`NaN >= x` 与 `NaN > x` 恒为 `False`。初版 `distributed/aggregator.py` 的 `pareto_frontier` 在遇到异常参数产生 `sharpe_ratio = NaN` 时，`any(_dominates(f, r))` 恒为 `False`，导致**所有 `NaN` 坏结果被 100% 当作“非支配最优解”保送进帕累托前沿**[cite: 1]！此外，缺乏对 Worker 重试重复结果（Exactly-Once Effect）和任务丢失的校验[cite: 1]。

* **改进前代码 (Before)**：
  ```python
  # distributed/aggregator.py (v0.1 - NaN 会直接穿透支配检查进入 frontier)
  def pareto_frontier(results: list[dict]) -> list[dict]:
      frontier: list[dict] = []
      for r in results:
          if any(_dominates(f, r) for f in frontier):
              continue
          frontier = [f for f in frontier if not _dominates(r, f)]
          frontier.append(r)
      return frontier
  ```

* **改进后代码 (After)**：
  ```python
  # distributed/aggregator.py (v0.2 - 严格校验有限数值、确定性 Tie-Breaker 与 job_id 完整性)
  def is_valid_result(r: dict) -> bool:
      for k in REQUIRED_SCALAR_KEYS:
          val = r.get(k)
          if val is None or not isinstance(val, (int, float)) or not math.isfinite(val):
              return False
      return r["max_drawdown"] <= 1e-12

  def verify_grid_completeness(expected_job_ids: list[str], raw_results: list[dict]) -> dict[str, dict]:
      deduped: dict[str, dict] = {}
      for res in raw_results:
          jid = res.get("job_id")
          if not jid:
              raise ValueError("Worker result missing canonical 'job_id'")
          if jid in deduped:
              for k in REQUIRED_SCALAR_KEYS:
                  if deduped[jid][k] != res[k]:
                      raise RuntimeError(f"Non-deterministic retry detected for job_id={jid}")
          else:
              deduped[jid] = res
      if set(expected_job_ids) != set(deduped.keys()):
          raise RuntimeError("Grid completeness violation: expected != completed job IDs")
      return deduped
  ```

---

## 四、 四层分布式正确性验证框架全景 (Fixes #3)

在 `tests/test_distributed_correctness_framework.py` 中，我们将上述所有教训固化为 7 组自动化测试：

| 验证层级                   | 测试函数                                             | 核心检验机制与目标                                                                                                                         |
| :------------------------- | :--------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------- |
| **1. 语义正确性 (Oracle)** | `test_differential_against_independent_oracle`       | 引入零依赖的手工基准模型（Independent Reference Oracle），进行 `Single` vs `Ray` vs `Oracle` 三方比对，防止生产引擎共享同一逻辑错误        |
| **2. 事件一致性 (Replay)** | `test_event_level_replay_and_state_hash_consistency` | 对每个时间步 $t$ 的定点数账本状态计算累积 `SHA-256` 哈希 $H_t$，证明单机与 Ray 在每一笔订单、拒单和状态转移上 100% 比特级重合              |
| **3. 分片与调度无关性**    | `test_metamorphic_partition_invariance`              | **变形测试（Metamorphic Testing）**：改变 Worker 数量（`W=1` vs `W=4`）、打乱提交顺序、注入重复任务、改变 `batch_size`，结果与哈希保持不变 |
| **4. 状态隔离性**          | `test_state_isolation_a_b_a`                         | 执行 `A -> B -> A` 序列，证明先后两次 `A` 的事件流与状态哈希严格一致，无状态残留（State Leakage）                                          |
| **5. 时序无未来函数**      | `test_no_look_ahead_bias_prefix_invariance`          | 将 $T$ 时刻之后的价格放大 50 倍，断言 $[0, T)$ 区间内的所有交易事件与净值曲线纹丝不动                                                      |
| **6. 预热窗口对齐**        | `test_warmup_window_alignment`                       | 强制 `warmup_bars=60`，确保快慢不同周期的均线参数在完全相同的样本区间上进行公平评估                                                        |
| **7. 变异与故障注入**      | `test_mutation_catches_nan_and_dropped_jobs`         | **变异测试（Mutation Testing）**：故意注入 `NaN` 夏普比率、缺失 `job_id`、不一致重试及超额杠杆，验证防御机制 100% 捕获异常                 |