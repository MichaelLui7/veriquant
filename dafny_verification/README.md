# Dafny 形式化验证模块

用 **Dafny 4.x** 对量化交易系统的核心风控逻辑做**定理级证明**，并通过
`dafny translate py` 将验证通过的代码**直编为 Python 模块**，供回测引擎直接
`import` 调用。证明过的逻辑不是"另外重写的一份"，而是**运行时实际执行的那一份**。

## 为什么用定点数而不是浮点数

所有金额/价格都用**放大 `SCALE = 10000` 倍的整数**表示（如 `1.0000` 记为
`10000`）：

- 规避 IEEE-754 浮点精度丢失导致的不变式失效；
- 让 SMT 求解器（Z3）在**纯线性整数算术**上做判定，证明秒级完成且结果确定。

## 模块与定理

| 文件                    | 证明的内容                                                                                                                                                             |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Types.dfy`             | 定点数缩放、账户/订单/状态机的领域模型                                                                                                                                 |
| `AccountInvariants.dfy` | **资金守恒**（可用现金 + 冻结现金，任何锁仓/解仓都不凭空增减）、**无透支**（`cash/lockedCash/positionValue` 恒非负）、**杠杆上限不变式**（总敞口 ≤ 净资产 × 最大杠杆） |
| `OrderStateMachine.dfy` | 订单状态机只向终态单向推进；**成交**把冻结资金转为持仓且净资产守恒；**撤销**精确释放剩余冻结资金、且终态无后继迁移（**防双花**）                                       |
| `StopLossBounds.dfy`    | **有界滑点假设下**的止损损失上界：`requires                                                                                                                            | ΔPrice | ≤ MaxGap` 时，最大亏损 ≤ `(入场价 - 止损价 + MaxGap) × 仓位` |
| `RiskGateway.dfy`       | 顶层事前风控网关 + 运行时测试方法（`{:test}`）                                                                                                                         |

### 关键设计点

- **杠杆上限用编译期常量 `MAX_LEVERAGE_BPS`（而非账户字段）**：使不变式
  `exposure ≤ equity × MAX_LEVERAGE_BPS` 成为**纯线性**比较。若用可变字段，
  乘积 `equity × maxLeverageBps` 会触发 Z3 的非线性整数算术（NIA）启发式搜索，
  导致证明变慢甚至超时。这一取舍在 `formal_verification_spec.md` 中有详细说明。
- **止损定理放在独立模块**：`StopLossBounds` 的结论含 `× 仓位`，是真正的非线性
  事实；它被单独验证，**不 import 进运行时网关**，避免其量词污染网关模块的 SMT
  上下文。
- **`{:vcs_split_on_every_assert}`**：让每个 `expect` 拆成独立的验证条件，既加速
  证明又能精确定位失败断言。

## 血泪史：与 Z3 非线性算术的三天拉锯战

> 这一节是本模块最值钱的部分——**从"0 errors"
> 到"0 errors"之间，我们被 Z3 坑得体无完肤**。如果你也在用 Dafny/Z3 做形式化验证，你也许会知道：
> **"0 errors"只是个幌子，背后是 Z3 的"0 errors"**。

### 1st Episode：一切"看起来"都对，除了那个方法死活要 60 秒

第一版把 `maxLeverageBps` 做成账户字段，`ValidAccount` 里赫然写着：

```dafny
(positionValue + lockedCash) * SCALE <= (cash + lockedCash + positionValue) * maxLeverageBps
```

`dafny verify` 各模块单独跑：`AccountInvariants` 秒过，`OrderStateMachine` 秒过，
连 `FullOrderLifecycle`（符号化参数、三次链式调用）都过了。唯独
`TestOrderFillAndCancel` —— 那个"锁仓 → 成交 → 撤销"的*具体数值*测试 —— 每次都在
`Verification ... timed out after 40 seconds` 里倒下。

最气人的是：**把这段方法原封不动复制到一个全新的、只有它一个方法的模块里，秒过。**
同样的代码，换个"邻居"就从闪电侠变成树懒。那一刻脑子里只有一句话：
"这跟代码逻辑没有半点关系，是 SMT 上下文的问题。"

### 2nd Episode：三个"以为修好了"的假动作

1. **甩锅给 `StopLossBounds`**。它是唯一含真非线性（`× 仓位`）的模块，第一反应是
   它 import 进来后，把那条非线性的量词公理塞进了网关模块。实验一测：单独把它
   import 进测试模块，确实也超时了！"抓到你了！"——于是把它请出网关模块。重新验证：
   **还是超时。** 抓到的是个从犯，不是主犯。

2. **上 `{:opaque}` 把乘积藏起来**。把 `equity × maxLeverageBps` 包进一个
   `{:opaque}` 函数，让 Z3 当它是原子项、别去展开。超时确实消失了——但换来的是：
   具体数值的 `ValidAccount(AccountState(100000, 0, 0, ...))` 前置条件**证明不了**了
   （藏起来之后连 `100000 × 20000` 都不给算了），`assert ok` 也崩了。顾此失彼。

3. **上 `--disable-nonlinear-arithmetic`**。运行时那几个文件瞬间全绿，还快得离谱。
   但它是实验性 flag，而且一开就把真正需要非线性的 `StopLossTotalBound` 给干掉了。
   "用一个实验性开关换一套证明"，这含金量，面试官会皱眉。

### 3rd Episode：真正的元凶

回到根本：`maxLeverageBps` 是**字段**，所以 `equity × maxLeverageBps` 是
**变量 × 变量**。关键在于链式调用之后——`TryLockOrderCash` 返回的新账户里，
`maxLeverageBps` 不再是字面量 `20000`，而是一个只通过 `ensures` 与旧值挂钩的
**符号量**。于是后续 `FillOrder`/`CancelOrder` 的推理里，`equity × locked.maxLeverageBps`
一头扎进 Z3 的**非线性整数算术（NIA）**——而 NIA 是不完备的、启发式的、耗时随心情的。

### 结局：

1. **把最大杠杆改成编译期常量 `MAX_LEVERAGE_BPS`** —— 右侧退化成 `equity × 20000`
   的线性式，验证秒级、确定。
2. **真正非线性的止损定理独立成模块** —— 需要 NIA 的东西自己关小黑屋单独验证，
   别进运行时网关的客厅。
3. **`{:vcs_split_on_every_assert}`** —— 把每个 `expect` 拆成独立验证条件，又稳又快。

**在形式化验证里，变量的身份(字段 vs 常量)不只是"值能不能变"的问题，
它直接决定我们的证明是线性还是非线性。** 

## 构建

```bash
# Linux / macOS / CI
./dafny_verification/build_py.sh

# Windows PowerShell
powershell -ExecutionPolicy Bypass -File dafny_verification/build_py.ps1
```

脚本会：

1. 逐一 `dafny verify` 每个 `.dfy`，把求解器输出追加到
   `docs/verification_report.txt`；
2. `dafny translate py` 把 `RiskGateway.dfy` 编译到
   `risk_control/_generated/verified_risk-py/`。

## Python 侧调用

`risk_control/gateway.py` 负责 float ↔ 定点数的转换，并对生成的
`VerifiedRisk.default__` 做一层薄封装：

```python
from risk_control.gateway import Account, RiskGateway

gw = RiskGateway(Account(cash=10.0))
approved, acc = gw.pre_trade_check(3.0)   # 冻结 3.0，返回 (True, 新账户)
approved, acc = gw.pre_trade_check(30.0)  # 超 2x 杠杆，返回 (False, 原账户)
```

验证一致性（Python 桥接层 ↔ Dafny 生成代码）：

```bash
python tests/test_dafny_bridge.py
```
