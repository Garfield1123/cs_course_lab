# 逐查询接口：已提供策略语义，尚未接入 GateANN

`adaptive_budget.choose_budget(selectivity_fraction) -> int` 是可执行的纯函数；`workload_budget(selectivities) -> int` 仅允许整档位于同一阈值段。Python runner 在启动整档查询进程前选择 L。当前没有修改 GateANN 的逐查询循环、索引结构或搜索内核。

真正逐查询实验应在同一索引实例内对交错的 low/medium/high 查询逐条选择 L，不能每条 query 启动一次进程；否则索引加载成本污染比较。

## 待实施的 C++ 接口建议

```cpp
// Proposed interface only; not compiled or integrated in this deliverable.
struct BudgetDecision {
    uint32_t L;
    double estimated_selectivity;
};
BudgetDecision select_budget(double s); // reject NaN/out-of-range; .01/.05 boundaries
```

可先新增自有头文件 `optimization/include/selectivity_budget.h`，再在用户实际源码确认后接入，不能现在生成声称可应用的第三方 diff。

## 需要核对的集成位置

1. 课程适配器已确认调用 `systems/GateANN-public/build/tests/search_disk_index_yfcc`。首先在本地对应的 `tests/search_disk_index_yfcc.cpp` 查位置参数解析、外层 L 循环、query 循环、计时范围与统计汇总。上游当前公开 README 也列出该文件，但课程固定提交的源码尚未在本会话读取，函数名/行号/调用签名待核对。
2. 在每条查询的过滤条件已解析之后、实际搜索调用之前计算 s_i 和 L_i。不可将外层 sweep 的 L 一次覆盖成一个平均值。
3. 课程单标签查询可以用标签计数 `count(label)/N`。标签计数在索引/数据准备阶段构建并保存，运行时 O(1) 查表。多标签 conjunction 必须估计交集基数，不得把各标签 s 相加或直接拿最小值当真值。使用真实 cardinality 的离线查表属于 oracle 辅助，应报告其预处理成本和可部署性。
4. 搜索 scratch/候选池/结果数组容量按最大 L=640 或真实接口要求分配；逐查询传入 L_i。检查候选池、visited 状态、线程本地内存、边界清理及最终 top-k。不能只改一个打印参数；确认实际搜索路径消费 L_i。
5. 固定 L 和 adaptive 用同一二进制、同一交错查询顺序、同一索引加载与缓存协议，保留 query_id 到 GT 的一致映射。过滤选择率估计、策略选择的在线成本要计入 query time；另可记录 search-only time，不能静默排除策略开销。
6. 输出每条 query 的 query_id、filter_id、s_i、L_i、策略耗时、搜索耗时、logical IO、Recall@10 或返回 ID；汇总整流 elapsed query time 和 QPS。新增输出到独立文件，避免破坏课程 8 列解析器。按查询时间算平均和分位数，不用 QPS 倒数冒充尾延迟。
7. 测试 .009999/.01/.049999/.05、空集合、缺失计数、非法 s、全匹配、零匹配、混合跨段、并发状态复用。预算高于可用候选数的行为也要核实。

## 可接受的表述

当前：实现了基于负载选择率的搜索预算调度与对照实验工具；逐查询内核接入未完成；实测尚待 Ubuntu 执行。

后续仅在编译、真实执行和输出核验完成后，才能写“实现 GateANN 逐查询自适应预算”；目前的三档观测拼合不能证明真正混合流的逐查询效果或其运行开销。

源码位置参考：[GateANN 官方仓库](https://github.com/GyuyeongKim/GateANN-public)。注意当前公开版本不等于课程固定版本。
