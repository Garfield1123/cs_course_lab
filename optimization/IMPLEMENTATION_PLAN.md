# GateANN adaptive budget 实施记录

依据用户 2026-11-10 的完整规格立即实施，不等待额外方案确认。

## 设计与边界
使用 Python 3.10+ 标准库调用现有 GateANN adapter。只新增 optimization/ 与 scripts/optimization/，不改 README、报告、原适配器、第三方系统。先实现 workload-level；逐查询接口作为独立策略函数和集成说明，不宣称内核已接入。

选择这个路径是因为课程适配器已经支持任意正整数 L；直接改 GateANN 内核增加风险且当前没有用户虚拟机。8 个 bucket/L 单元各重复 3 次，策略表引用同一批观测。旧正式结果没有已核验的完整 provenance，因此只作历史参考。

## 实施任务
- [x] 1. 策略与验收测试：阈值 0.01/0.05、非法选择率、跨阈值负载、24 个唯一任务、CSV 严格检查、统计单位。
- [x] 2. Runner：plan/check/run/resume，课程真实参数，源文件与输入 SHA256，独立 run-id，原始日志，错误中止，不覆盖旧结果。
- [x] 3. 分析：8 单元 sweep、3 策略按档与等权混合、3 repeats 的 median/min/max/range、共享观测标记。
- [x] 4. 实验方案、逐查询接入建议、Ubuntu 命令、新文件安装器；Windows 可运行测试通过，Linux 实测仍未执行。

## Review focus
阈值单位混淆；旧/失败结果被静默复用；CSV 错行和 NaN；用进程时间作查询延迟；QPS 错误算术平均。分别通过边界、resume、严格解析、原始输出核对、加权混合测试验证。

## 环境核对记录
Gitee 上游 HEAD e44eab5d1b040ffdebc80374a13b304a9c4d37de，可完整读取。
GitHub 用户仓库 ls-remote 曾返回 2cf9426e73dd0c2d8ce7a44cd2d1220fde501370，但三次 clone 均连接失败；未取得该版本文件。
Windows 无可用 Ubuntu 会话/数据/索引。原有 test_doctor、test_build_retry 在 Windows 导入 resource 失败，无法声称原测试通过。
本次独立分支 experiment/gateann-selectivity-budget 位于上游的独立克隆。

## 完成记录与复核
新增 19 个测试通过，包括合成适配器的 24 次真实子进程调用、完整统计与 resume；这些不是 GateANN 性能数据。两份 shell 包装器语法检查通过。
独立复核发现 4 项重要问题，已用失败测试复现并修复：邻接缓存/新增索引文件未覆盖；中断/失败日志可能丢失覆盖；多余原始测量和 NaN 诊断被接受；重复 CSV 表头/行宽错误被接受。
未留下已知次要复核问题。原有 Linux-only tests 在 Windows 的 resource 导入失败，保留为平台限制，不改课程代码绕过。
实施决策：保留独立分支及仅新增文件补丁，不合并、不推送；旧正式结果仅作为用户提供的历史参考；真实实验须在用户 Ubuntu 执行。
