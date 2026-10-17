# 形式化验证白皮书

本文记录 `dafny_verification/` 中每条定理的**前置假设、结论与证明策略**，以及
Z3 的验证统计。

## 1. 定点数约定

- `Types.SCALE = 10000`：金额/价格放大倍数。`1.0000` 记作整数 `10000`。
- `Types.MAX_LEVERAGE_BPS = 20000`：系统级最大杠杆（基点），`2.0x`。
- 全部算术为 **Dafny `int`（无界整数）**，不存在溢出；乘/加均为线性运算
  （常数 × 变量），Z3 在 LIA（线性整数算术）内即可判定。

## 2. 账户不变式 `AccountInvariants.ValidAccount`

对任意账户 `acc = AccountState(cash, lockedCash, positionValue)`：

```
cash >= 0 && lockedCash >= 0 && positionValue >= 0 &&
(positionValue + lockedCash) * SCALE <= (cash + lockedCash + positionValue) * MAX_LEVERAGE_BPS
```

- **无透支**：三个余额分量恒非负。
- **杠杆上限**：总敞口（持仓市值 + 冻结现金）≤ 净资产 × 最大杠杆。

> **设计取舍（为什么 `MAX_LEVERAGE_BPS` 是常量）**：若把最大杠杆作为账户字段
> `maxLeverageBps`，则不等号右侧 `netEquity × maxLeverageBps` 是**两个变量之积**，
> 触发 Z3 的非线性整数算术（NIA）启发式。NIA 是不完备的、耗时不确定，会在链式
> 调用（锁仓→成交→撤销）时超时。改为编译期常量后，右侧退化为 `netEquity × 20000`
> 的线性式，验证**秒级、确定**。系统级风控策略（而非逐账户）正是事前风控网关的
> 典型形态；逐账户限额可通过对暴露上限做线性缩放叠加实现。

## 3. 资金守恒与状态迁移

定义 `TotalCash = cash + lockedCash`，`NetEquity = cash + lockedCash + positionValue`。

| 操作 | 不变量 |
| --- | --- |
| `TryLockOrderCash`（冻结订单现金） | `TotalCash`、`NetEquity` 守恒；失败则状态不变；`success ⟺ (notional ≤ cash ∧ 杠杆通过)` |
| `ReleaseLockedCash`（解冻） | `TotalCash`、`NetEquity` 守恒；`success ⟺ release ≤ lockedCash` |
| `FillOrder`（成交） | `NetEquity` 守恒（冻结资金转为持仓，`lockedCash -= f`，`positionValue += f`） |
| `CancelOrder`（撤销） | `TotalCash` 守恒；`locked = 0`；状态为终态 `Cancelled` |

**防双花**：`CancelOrder` 后订单为终态，且 `OrderStateMachine.TerminalStaysTerminal`
证明终态无任何合法后继迁移，故冻结资金只会被精确释放一次。

## 4. 有界滑点下的止损边界

止损单在真实市场（隔夜跳空、流动性枯竭）下**无法**保证亏损不超阈值。诚实的定理
是**有条件的**——把假设显式写成 `requires`：

```dafny
lemma StopLossTotalBound(entryPrice, stopPrice, fillPrice, position, maxGap)
  requires entryPrice >= stopPrice
  requires fillPrice >= stopPrice - maxGap   // 成交价最多向下跳空 maxGap
  requires position >= 0 && maxGap >= 0
  ensures (entryPrice - fillPrice) * position
       <= (entryPrice - stopPrice + maxGap) * position
```

多头止损的每单位损失 `entryPrice - fillPrice` 被 `entryPrice - stopPrice + maxGap`
界定：止损价以下最多再滑出 `maxGap`。该结论对 `position` 的乘积是**真非线性**事实，
因此本文件独立成模块单独验证，不引入运行时网关的 SMT 上下文。

## 5. 验证统计（`dafny verify`，Dafny 4.9.0）

| 文件 | 验证条件（VC） | 错误 | 备注 |
| --- | --- | --- | --- |
| `Types.dfy` | 0 | 0 | 纯类型定义 |
| `AccountInvariants.dfy` | 2 | 0 | |
| `OrderStateMachine.dfy` | 3 | 0 | |
| `StopLossBounds.dfy` | 2 | 0 | 非线性定理，独立验证 |
| `RiskGateway.dfy` | 38 | 0 | 网关 + 3 个 `{:test}` 运行时测试 |

完整输出见 `docs/verification_report.txt`。
