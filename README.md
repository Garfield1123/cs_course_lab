# 基于 SSD 的过滤向量检索系统实验与性能分析

Computer Systems Design Course Lab

## 1. 项目简介

本项目基于课程提供的实验框架，对两种 SSD 驻留式过滤向量检索系统 **PipeANN-Filter** 和 **GateANN** 进行部署、功能验证及性能评估。

实验采用 YFCC 百万规模向量数据集，在不同过滤选择率（Selectivity）和搜索参数（L）下，分析两个系统的检索准确率、查询延迟、吞吐量、逻辑 I/O 开销及资源占用情况。

本仓库在原始课程项目的基础上，增加了正式实验结果、环境记录和 GateANN 兼容性修复补丁，并对实验现象与潜在优化方向进行了分析。

## 2. 与原始课程仓库的区别

本仓库保留原始课程框架，主要新增内容如下：

| 内容 | 本仓库完成的工作 |
|---|---|
| 实验环境 | 在 VMware Ubuntu 虚拟机中搭建并验证运行环境 |
| 系统部署 | 完成 PipeANN 和 GateANN 的构建与运行 |
| 功能验证 | 在 Debug 数据集上验证两个系统的检索正确性 |
| 正式实验 | 在百万规模 YFCC 数据集上运行对比实验 |
| 性能分析 | 比较 Recall@10、Latency、QPS 和逻辑 I/O |
| 兼容性修复 | 保存 GateANN Linux AIO 相关源码补丁 |
| 实验材料 | 新增正式实验结果 CSV 和环境信息 |
| 优化分析 | 提出基于 Selectivity 的自适应搜索预算方案 |

**说明：** 本项目的主要工作是实验复现、系统对比及性能分析，不声称重新实现 PipeANN 或 GateANN 的核心搜索算法。

## 3. 实验环境

| 项目 | 配置 |
|---|---|
| 虚拟化平台 | VMware |
| 操作系统 | Ubuntu 22.04.5 LTS |
| Linux Kernel | 6.8.0-138-generic |
| CPU | AMD Ryzen 7 6800H，分配 4 vCPU |
| 内存 | 约 7.7 GiB |
| 编译器 | GCC/G++ 11.4.0 |
| I/O 后端 | Linux AIO |
| 数据集 | YFCC，1M × 192D，uint8 |

完整环境记录见 `experiments/20261004-173150/environment.txt`。

## 4. 实验设计

### 4.1 数据集与过滤负载

正式实验使用 100 万条、192 维的 YFCC 向量数据，通过真实标签构造不同过滤选择率的查询负载。

| 工作负载 | Selectivity 范围 |
|---|---|
| Low | 0.250%–0.851% |
| Medium | 1.765%–4.995% |
| High | 7.074%–17.089% |

每组工作负载包含 200 条查询。

### 4.2 搜索参数

主要实验参数：

- Top-K：10
- 查询线程数：1
- Beamwidth：8
- 每组配置重复次数：3
- PipeANN：L = 20、40、80（High）；其他负载采用 L = 40
- GateANN：L = 160、320、640（High）；其他负载采用 L = 320

由于两套系统对搜索参数 L 的实现和工作量定义不同，不直接将相同 L 数值作为公平性能比较依据，而是重点比较相近 Recall 水平下的延迟与 I/O 开销。

## 5. 实验结果

### 5.1 High Selectivity 下的性能比较

以下数据为三次运行结果的中位数。

| 系统 | L | Recall@10 | 平均延迟 | 平均逻辑 I/O |
|---|---:|---:|---:|---:|
| PipeANN | 20 | 79.80% | 7.159 ms | 79.30 |
| PipeANN | 40 | 92.00% | 10.187 ms | 123.30 |
| PipeANN | 80 | 97.20% | 16.616 ms | 212.50 |
| GateANN | 160 | 81.30% | 4.630 ms | 24.62 |
| GateANN | 320 | 93.20% | 8.696 ms | 46.71 |
| GateANN | 640 | 98.65% | 14.925 ms | 88.89 |

在相近 Recall 水平下，GateANN 在本次实验中表现出更低的查询延迟和报告的逻辑 I/O 数量。

需要注意，不同系统的内部 I/O 统计口径可能存在差异，不能直接将逻辑 I/O 差异等同于物理磁盘访问量差异。

### 5.2 不同 Selectivity 下的性能

采用代表性配置 PipeANN L=40、GateANN L=320。

| 系统 | Selectivity | Recall@10 | 延迟 |
|---|---|---:|---:|
| PipeANN | Low | 98.60% | 5.719 ms |
| PipeANN | Medium | 90.80% | 13.725 ms |
| PipeANN | High | 92.00% | 10.187 ms |
| GateANN | Low | 34.30% | 1.828 ms |
| GateANN | Medium | 72.05% | 3.759 ms |
| GateANN | High | 93.20% | 8.696 ms |

在本次固定搜索预算设置下，GateANN 在强过滤条件下出现明显的 Recall 下降，而 PipeANN 保持了较高的检索准确率。

不同 Selectivity 负载由不同真实标签构成，因此结果也可能受到标签分布和查询难度影响，不能完全归因于选择率变化。

完整结果见 `experiments/20261004-173150/results.csv`。

## 6. GateANN Linux AIO 兼容性修复

在课程实验环境中，GateANN 的 Linux AIO 相关代码应用了一处兼容性补丁：

原始代码：

`cb.data = (void *) &reqs[j];`

修复后：

`cb[j].data = (void *) &reqs[j];`

修复内容是为当前 I/O 请求设置对应控制块的用户数据指针，不涉及 GateANN 核心搜索算法的修改。

补丁保存在：

`patches/gateann-aio-compat.patch`

该补丁可用于在对应的 GateANN 源码版本上重现本次兼容性修改。

## 7. 实验复现

本项目使用课程提供的运行脚本。

主要流程如下：

1. 准备 Ubuntu 编译与运行环境。
2. 获取课程提供的 YFCC 数据集及预构建索引。
3. 执行 `bash scripts/check_dataset.sh` 检查数据集。
4. 执行 `bash scripts/prepare_pipeann.sh` 和 `bash scripts/prepare_gateann.sh` 准备两个系统。
5. 执行 `bash scripts/run_debug_validation.sh` 验证功能正确性。
6. 执行 `bash scripts/check_indexes.sh` 检查正式实验索引。
7. 执行 `bash scripts/run_formal_experiments.sh` 运行正式实验。

大型数据集、预构建索引、编译产物及运行时目录未包含在本仓库中，需要按照课程原始说明另行准备。

## 8. 优化方向

根据实验中 GateANN 在强过滤负载下 Recall 降低的现象，提出一种基于 Selectivity 的自适应搜索预算方案。

基本思路是在过滤选择率较低时分配更大的搜索预算，以尝试改善过滤条件下的候选节点探索能力；在选择率较高时维持较小预算，控制查询开销。

**本优化方案目前属于设计与分析阶段，尚未完成实现及补充实验验证，不构成已证实的性能提升。**

## 9. 仓库结构

- `adapters/`：实验系统适配代码
- `config/`：实验配置
- `datasets/`：数据集相关配置与工具
- `docs/`：课程文档与实验说明
- `scripts/`：系统准备、验证和实验运行脚本
- `tests/`：测试代码
- `experiments/20261004-173150/`：本次正式实验结果及环境记录
- `patches/`：GateANN Linux AIO 兼容性补丁

PipeANN 与 GateANN 的完整上游源码位于本地实验环境的 `systems/` 目录中，该目录未作为本仓库的普通 Git 文件提交。

## 10. 项目来源与说明

本项目基于课程提供的 [fvs-course-lab](https://gitee.com/wei-fangyu/fvs-course-lab) 实验框架。

PipeANN 与 GateANN 为已有研究系统。本仓库中的原始课程代码及相关第三方代码，其版权和许可归各自权利人所有。

本仓库旨在记录课程实验复现过程、性能评估结果和实验分析工作。
