# 优化实验结果归档

本目录保存 `budget-20261110-143518-ec7e5e19` 的24次真实测量。manifest、CSV、command.json和run.log保持原始字节内容。`ARTIFACTS.json` 将原始Linux路径映射到本仓库内的证据路径，并列出72个原始文件的SHA256。

本目录的 `.gitattributes` 禁用证据文件的换行转换，防止跨平台检出改变原始文件哈希；Git补丁将这些文件作为二进制保存，CSV和JSON本身仍可直接阅读。

原manifest中的绝对路径是当时的运行记录。归档改变了文件存放位置，不能将本目录直接传给原runner的analyze命令；在原Ubuntu机器上，应对 `course_runs/optimization/budget-20261110-143518-ec7e5e19` 运行analyze。查看结果可直接使用本目录内的CSV及[补充实验说明](../../../docs/gateann-budget-results.md)。

三种策略引用同一批观测，共享行不是独立重复实验；混合行是分档结果离线合成。延迟=1000/QPS，逻辑I/O不代表物理磁盘读次数。数据、索引、二进制和第三方源码均不在此目录。
