# 分布式回测调度层（Ray）

Master-Worker 架构：Master 把**参数空间**（以及可扩展的**截面标的**）切成独立任务，
扇出到 Ray 集群；Worker 是无状态的，读同一份行情数组做确定性回测，只返回标量指标。

## 为什么不按时间切片

策略是**有状态的**：均线依赖历史窗口，昨天持仓影响今天资金。按时间切片极易造成
跨切片的持仓状态不一致，甚至引入**未来函数（Look-ahead Bias）**。因此只按：

- **参数空间**（网格搜索 / 贝叶斯优化）
- **截面标的**（多资产横截面）

两个维度切分，每个 Worker 都完整跑一遍共享行情、只是参数/标的不同。

## 零拷贝共享内存

行情矩阵用 `ray.put()` 只放**一次**进 Plasma Object Store；调度器把 ObjectRef 传给
任务，Ray 在同节点上把**只读共享内存视图**交给 Worker（自动解引用，零反序列化）。
`distributed/shared_memory.py` 封装了这条 `put` 路径。

## 确定性（分布式 == 单机）

Worker 是无状态纯函数：`float64` 全程、无 RNG、无归约顺序依赖。因此分布式结果与单机
**逐比特一致**，由 `tests/test_distributed_consistency.py` 断言：

```bash
python tests/test_distributed_consistency.py   # 9 组参数，bit 级一致
python tests/benchmark_ray.py                  # 单机 vs Ray 加速比
```

## 模块

| 文件 | 职责 |
| --- | --- |
| `cluster.py` | Ray 集群初始化 + 资源探针（幂等 `ray.init`） |
| `shared_memory.py` | `ray.put` 行情零拷贝封装 |
| `worker.py` | `@ray.remote` 无状态回测 Worker |
| `aggregator.py` | 按 Sharpe 排序 + 帕累托前沿筛选 |
| `scheduler.py` | `DistributedBacktestEngine` 网格搜索扇出 |

## 加速比说明

在这个玩具级**向量化**回测（O(n) 的 numpy cumsum/cumprod）上，任务本身是**内存带宽
受限**的，8 核实测约 **2.4x**。这不是 Ray 的问题——内存受限的 numpy 单核已接近带宽
上限，多进程只会争抢带宽。真正的近线性加速出现在**计算受限**的任务（事件驱动逐 bar
循环、蒙特卡洛 bootstrap、多资产截面）上。基准脚本把这些现实写进了注释里，避免
"6.8x" 这类营销数字经不起追问。
