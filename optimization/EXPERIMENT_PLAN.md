# GateANN Selectivity-aware Search Budget 优化实验方案

日期：2026-11-10。状态：已交付 workload-level runner；尚无本次优化的 GateANN 实测结果。

## 1. 核实范围与限制

- 用户目标仓库：`/home/liuliyuan/cs_system_lab/fvs-course-lab`；GitHub `https://github.com/Garfield1123/cs_course_lab`。
- 用户 GitHub HEAD 曾通过只读查询取得 `2cf9426e73dd0c2d8ce7a44cd2d1220fde501370`，但文件克隆连续连接失败；不能声称已检查该提交的文件、用户 CSV 或虚拟机。
- 已完整检查课程 Gitee 上游 `https://gitee.com/wei-fangyu/fvs-course-lab.git`，提交 `e44eab5d1b040ffdebc80374a13b304a9c4d37de`。脚本在该上游的独立分支 `experiment/gateann-selectivity-budget` 编写；没有推送。
- 核实文件：`adapters/gateann_adapter.py`、`adapters/_common.py`、`adapters/versions.json`、`scripts/run_formal_experiments.sh`、`scripts/collect_results.py`、`config/experiments.env`。
- 上游固定 GateANN 提交 `71e87cbf0e25c0400c0109dd25a64a7c4dccc9dd`。没有取得该第三方源码或 Linux 可执行程序，不能声称做过内核编译/性能测试。集成前 `check` 会在用户机器上核对实际命令。
- 用户已有 `patches/gateann-aio-compat.patch`；上游命名为 `patches/gateann_aio_compat.patch`。本方案不修改任何补丁，审计时匹配两种命名并记录 SHA256。AIO 兼容修复不算算法优化。
- 原 README、实验报告、正式实验结果、课程适配器均不修改。

## 2. 问题、假设与策略

现有正式实验（用户提供，未在本会话重新验证）：

| 档位 | Selectivity | L=320 Recall@10 | latency ms | logical IO/query |
|---|---|---:|---:|---:|
| Low | 0.250%–0.851% | 34.30% | 1.8282 | 4.38 |
| Medium | 1.765%–4.995% | 72.05% | 3.7594 | 16.75 |
| High | 7.074%–17.089% | 93.20% | 8.6957 | 46.71 |

候选规则：s < 0.01 用 L=640；0.01 ≤ s < 0.05 用 480；其余用 320。s 是匹配基数/1,000,000 的比例，不是百分数，不是 Recall，不从 ground truth 推断。s=0 也返回 640，但无法凭预算产生不存在的合法邻居。

待检验假设：在 Low/Medium 增大 L 能提高 Recall，代价是查询时间/I/O；High 保持 320 可减少相对统一 640 的开销。640/480/320 和阈值均为预设候选，不能称最优或已有效。若 Recall 无改善，或改善小于可见波动，或者成本过高，就报告未支持假设。

第一版按整档负载选择一次 L，名称必须为 **workload-level budget selection**。读取真实 `labels.csv` 的全部 selectivity，只有所有标签落在同一策略分段时才接受。跨段则停止，不使用中位数掩盖混合选择率。纯函数 `choose_budget(s)` 可被后续逐查询实现复用其语义，但没有接入 GateANN。

## 3. 公平对照与去重

| 档位 | 唯一待测 L | fixed320 引用 | fixed640 引用 | adaptive 引用 |
|---|---|---|---|---|
| Low | 320,480,640 | Low/320 | Low/640 | Low/640 |
| Medium | 320,480,640 | Medium/320 | Medium/640 | Medium/480 |
| High | 320,640 | High/320 | High/640 | High/320 |

8 个唯一单元 × 3 repeats = **24 次进程执行、4800 条计入统计的查询**。每个 repeat 包含全部 8 单元，固定随机种子 20261110 在块内打乱顺序，manifest 保存顺序。每次适配器调用仅传一个 L，降低原有 High 多 L 顺序带来的缓存/加载顺序不一致。

策略分析只引用这 24 条观测，绝不另运行 27 次三策略查询。共享的观测在输出中标记 `observation_reused=true`，不能当作独立样本；adaptive 与 fixed640 的 Low，以及 adaptive 与 fixed320 的 High，本来就是同一个观测，其差值为零不构成新的实验发现。

旧正式实验 CSV 尚无已核验的原始日志、数据/索引/二进制哈希和相同执行顺序，因此不自动并入此次公平对照。新跑 320 是同一轮实验的同期对照，不是重复运行三套基线。仅 `resume` 可跳过本次 manifest 已完成且哈希核验通过的单元。不导入匿名旧 CSV，不覆盖既有目录。

## 4. 固定条件与真实接口

数据：YFCC formal 1M×192D uint8；low/medium/high 各 200 queries。参数：threads=1、beamwidth=8、k=10、mem_L=0、cache_budget=0、full_adj_neighbors=32、mode=8、l2/pq、AIO、Release，重复 3 次。

课程入口（Low/480 示例）：

```bash
python3 adapters/gateann_adapter.py search \
  --repo "$PWD/systems/GateANN-public" \
  --dataset-root "$PWD/datasets/yfcc_course_v1" --tier formal \
  --run-root "$PWD/course_runs" --threads 1 --beamwidth 8 --k 10 \
  --bucket low --L 480 --mem-L 0 --cache-budget 0 \
  --full-adj-neighbors 32 --run-id UNIQUE_ID
```

适配器实际组装的位置参数，依次为：

```text
search_disk_index_yfcc uint8 INDEX_PREFIX 1 8 QUERY_U8BIN
  BASE_METADATA_SPMAT QUERY_METADATA_SPMAT GT_IDS_IBIN
  10 l2 pq 8 0 0 32 L
```

`--L` 接受正整数列表，没有只允许 160/320/640 的限制，故 480 在课程 harness 上可表达。runner 的 `check` 会运行 `search --help`、doctor 及 8 条 `--dry-run`，逐字核对实际二进制参数；之后真跑仍可能暴露二进制/索引问题，不能把 dry-run 当成性能验证。

负载结构：`datasets/yfcc_course_v1/formal_1000000/` 下有 `base.u8bin`、`base.metadata.spmat`、`base.labels.txt`；`workloads/{low,medium,high}/` 各有 `query.u8bin`、`query.metadata.spmat`、`query_filters.csv`、`labels.csv`、`ground_truth.ids.ibin`、`ground_truth.diskann.bin`。

u8bin/ibin 头为两个小端 uint32，spmat 头为三个小端 int64。课程 validator 要求每个查询单标签（query metadata nnz=200）。已知 labels.csv 必需字段为 `selectivity,query_count`；query_filters.csv 的具体列名尚未取得真实文件，runner 只核验存在并哈希，不猜测列名。原 adapter 的 selectivity_median 是标签选择率中位数，不保证查询加权；本策略只依赖全范围且同段。

正式索引前缀固定为 `course_runs/indices/gateann/formal_1000000/yfcc`，使用已有索引。`--run-root` 同时决定索引与结果位置，不能随便换成空的新结果目录。

## 5. 计时、指标与统计

原始 GateANN 数值行共 8 列：L、QPS、Recall（0..1）、MeanIO、FilterSkips、IO time、Tunnel time、Process time。课程适配器将 Recall 乘 100，并计算 `mean_latency_us=1,000,000/QPS`。因此本次 `latency_ms=1000/QPS` 是单线程查询阶段的吞吐倒数，不是新增的逐查询平均/尾延迟测量。它与 QPS 不是独立证据。

CSV 身份字段：system/tier/bucket/queries/L/k/threads/beamwidth/system_commit；指标字段：qps/mean_latency_us/recall_percent/mean_ios；其余 `elapsed_seconds/peak_rss_kb/raw_log` 等保留在原始课程 CSV。`elapsed_seconds` 或 runner 的 `process_wall_seconds` 包含加载、初始化等，仅作成本诊断，严禁作为查询 latency。`mean_ios` 是逻辑请求数，不是 SSD 物理读次数。

每个 bucket/L 的四项指标分别统计 n=3、median/min/max/range（max-min）。Recall 差值单位是百分点；延迟差值 ms；QPS 差值 queries/s；IO 差值 requests/query。不对三个 QPS 做求和。

混合策略不是实际混合查询流运行：每 repeat 先按各档查询数加权 Recall、latency、IO，再算 `QPS_total=sum(n)/sum(n/QPS)`；再对 3 个 repeat 求 median/range。不能先对档位中位数做混合，也不能将档位 QPS 作算术平均。单独保留 per-bucket 为主要结论。

## 6. 缓存、成本与局限

不清 OS page cache，不申请 root，不改系统设置，不添加隐蔽 warmup。所有单元使用新进程；GateANN 自身初始化/预热行为仍由现有二进制决定。check 要求邻接缓存 `yfcc.full_adj.R32` 已存在且非空（课程《系统准备》记载该命名）；缺失时停止，由 START_HERE 中明确的一次准备查询生成，其记录不计入正式 24 次测量。运行前全量 SHA256 会读取数据和索引、影响 page cache，因此这是共同的非冷缓存协议，不能宣称冷启动 SSD 性能。若需要冷缓存实验，应另立协议、全部重跑。

24 次加载索引的成本可能显著大于查询阶段。仅按已有 L=320 延迟，三档 ×200×3 的查询阶段约 8.57 秒；它不是整个 sweep 的时长估计，也不能据此估计 480/640。更大 L 的成本待测；输入哈希按实际文件字节量顺序读取，数据/索引越大越耗时。不重建索引、不下载数据，结果主要为小型日志/CSV/manifest；若缺少邻接缓存，另有一次准备查询和缓存文件的成本。

同一虚拟机同一会话尽量空闲、接通电源，避免其他磁盘/CPU 任务。3 repeats 不足以作强统计显著性结论；200 queries、不同真实标签和固定阈值限制外推。使用同一查询集看现象并调参会过拟合，本轮不根据结果偷偷改阈值；若选择新阈值，标为后续调参并用保留查询集验证。

## 7. 原始证据与验收

实验目录：`course_runs/optimization/<id>/`。manifest 记录完整参数、顺序、时间、环境、课程和 GateANN 提交/状态、补丁/源码/二进制/数据/索引（含邻接缓存）SHA256、每单元状态、命令、输出哈希和原始结果路径。运行前后核对索引文件清单，新增文件也会触发停止；resume 核对机器标识哈希及线程环境。CSV 要求唯一完整表头和行宽，原始输出必须只有一条八列测量，所有数字有限且非负。

原始课程输出仍在 `course_runs/results/gateann/formal_1000000/<bucket>/<unique-run-id>/`，保存 command.json、run.log、results.csv。实验目录还有适配器 stdout/stderr 日志。不要只复制汇总 CSV 而丢失原始目录；分享时脱敏绝对路径，数据和索引不打包。

汇总文件：measurements.csv（24 行）、sweep_summary.csv（32 行）、strategy_measurements.csv（36 行含混合）、strategy_summary.csv（48 行）、paired_deltas.csv（24 行）。重复分析仅在内容一致时保持原文件；不同内容拒绝覆盖。

验收必须同时满足：
1. Ubuntu 上 `check` 成功，实际文件头、查询数、选择率、doctor、CLI 完全吻合。
2. 24 个唯一单元全部成功、每个恰好 1 条课程 CSV 和 1 条 GateANN 数值行；退出码 0，设置一致。
3. Recall 在 0..100、QPS>0、IO≥0、所有数值有限；原始数值行与 CSV 一致。
4. 无缺失 repeat、无 NaN、无重复基线；所有观测哈希核验成功。已有目录不会被覆盖。
5. 新增自动化测试通过；Ubuntu 上再跑原 tests。Windows 上原 tests 的 resource 模块不可用，不代表 Linux 测试通过。
6. 用 Low/Medium 的 Recall 增量与延迟/IO 代价判断假设；负结果同样保留。证据完成前不更新 README/报告，不宣称性能提升。
