# 在 Ubuntu 应用并运行

这是新增文件包，不包含数据、索引、第三方源码、旧 README 或报告。真实 GateANN 性能尚未运行。方案见 EXPERIMENT_PLAN.md，逐查询边界见 PER_QUERY_INTEGRATION.md。

## 安装

先准备文件，再执行安装命令。这里的 `~/Downloads/` 指 **Ubuntu 虚拟机里的** `/home/liuliyuan/Downloads/`，不是 Windows 的下载文件夹。创建 Git 分支不会自动下载实验文件。

完整交付包名为 `gateann-budget-delivery.zip`。如果在 Windows 下载，请先通过可用的虚拟机共享文件夹、复制粘贴或拖放，把它传入 Ubuntu。可先在 Ubuntu 执行 `mkdir -p "$HOME/Downloads"` 创建目标目录，再用文件管理器把 ZIP 放进去。若文件实际在 Ubuntu 的“下载”或桌面目录，也请先复制到上述明确路径。

将 ZIP 放好后，在 Ubuntu 执行：

```bash
python3 -m zipfile -e "$HOME/Downloads/gateann-budget-delivery.zip" \
  "$HOME/Downloads/gateann-budget-delivery"
ls -lh "$HOME/Downloads/gateann-budget-delivery/install_gateann_budget.py" \
  "$HOME/Downloads/gateann-budget-delivery/gateann-budget-experiment.tar.gz"
```

上一步应列出 **两个文件**：安装脚本和实验压缩包。任何一步出现 `No such file or directory`，先核实 ZIP 的实际位置或传输是否完成，暂不执行后面的安装命令。

也可以从对话中的直接链接分别取得 `install_gateann_budget.py` 和 `gateann-budget-experiment.tar.gz`，将两者都放到 Ubuntu 的 `~/Downloads/`；这种情况下，下面安装命令的两个路径去掉中间的 `gateann-budget-delivery/` 即可。

确认文件到位后，进入课程仓库。下面的分支命令可重复执行；分支已存在时直接使用它。未提交改动不用清除。

```bash
cd /home/liuliyuan/cs_system_lab/fvs-course-lab
git status --short
if git show-ref --verify --quiet refs/heads/experiment/gateann-selectivity-budget; then
  git switch experiment/gateann-selectivity-budget
else
  git switch -c experiment/gateann-selectivity-budget
fi
# 安全安装脚本会先检查所有目标文件；存在任何同名文件时整体停止。
python3 "$HOME/Downloads/gateann-budget-delivery/install_gateann_budget.py" \
  --archive "$HOME/Downloads/gateann-budget-delivery/gateann-budget-experiment.tar.gz" \
  --root "$PWD"
```

看到 `Installed 12 new files` 后再进入下一节。如果之前已经显示 `On branch experiment/gateann-selectivity-budget`，可以直接执行安装命令，无须再创建分支。安装前 `working tree clean` 是正常的，表示新增实验文件还没装进去。

安装只新增 optimization/ 和 scripts/optimization/。也可用补丁 `git apply --check` 后 `git apply`，二选一，不能重复安装。

## 验证与实际运行

```bash
python3 -m unittest discover -s optimization/tests -v
python3 -m unittest discover -s tests -v

# 不需要数据也能查看完整调度计划；不会执行查询。
python3 optimization/experiment.py plan

# 核实当地数据、索引、AIO 构建及 CLI；不执行搜索。
python3 optimization/experiment.py check

# 一次运行全部 8 单元 ×3，并自动生成三种策略统计。
bash scripts/optimization/run_budget_sweep.sh
```

不需要先运行原 `run_formal_experiments.sh`。不要再为 adaptive 单独跑三档查询。工具默认定位现有 `systems/GateANN-public`、`datasets/yfcc_course_v1` 和 `course_runs`；若实际位置不同，可给 check/run 加 `--gateann-repo /实际路径 --dataset-root /实际路径 --run-root /包含indices的路径`。这些选项不修改原配置。

每次打印 `course_runs/optimization/<id>`。分析完成会显示 `Validated 24 measurements`；只有这一步成功，才表示输出结构通过验收，不代表策略一定有效。

若 check 提示缺少 `yfcc.full_adj.R32`，说明邻接缓存尚未准备。你已经完成过正式实验，通常该文件已经存在。仅在缺失时执行一次下面的准备查询，日志独立保留且不计入 24 次测量；之后重新 check/run。不要删除已有缓存：

```bash
python3 adapters/gateann_adapter.py search \
  --repo "$PWD/systems/GateANN-public" \
  --dataset-root "$PWD/datasets/yfcc_course_v1" --tier formal \
  --run-root "$PWD/course_runs" --bucket high --threads 1 --beamwidth 8 \
  --k 10 --L 320 --mem-L 0 --cache-budget 0 --full-adj-neighbors 32 \
  --run-id "budget-cache-prep-$(date +%Y%m%d-%H%M%S-%N)"
```

若使用自定义系统/数据/run-root 路径，准备命令也要使用相同路径。若实际二进制使用不同缓存命名，请保留报错和文件清单核对，不要改名伪装为课程缓存。

## 继续或重做分析

将下面的 `实际ID` 换成真实目录名，不要原样粘贴。

```bash
python3 optimization/experiment.py resume \
  --experiment-dir "$PWD/course_runs/optimization/实际ID"

# 已完成的 sweep 仅重新核验/分析，不发起任何 GateANN 查询。
bash scripts/optimization/run_adaptive_experiment.sh \
  --experiment-dir "$PWD/course_runs/optimization/实际ID"
```

resume 会再次核验输入全量哈希、索引文件清单、机器与线程环境，跳过已完成的相同观测。若失败/中断单元已留下原始目录或 adapter.log，会停止，保留证据；启动一个新实验 ID 重跑，不自动删除/覆盖失败文件。若输入、系统或源码变化，也应新开实验。不要并发运行同一 manifest；当前工具为单进程单操作者使用。

## 查看结果并提交代码

优先查看 `sweep_summary.csv`、`strategy_summary.csv`、`paired_deltas.csv`，再检查原始日志。Recall 的差值单位是百分点，延迟为 ms。混合行是分档观测推导值，非混合流实测。

只暂存新增源文件：

```bash
git add optimization scripts/optimization
git diff --cached --stat
```

检查无数据/索引/systems 后再自行提交。不要 `git add -f systems`，不要上传数据或索引，不改原 README/报告。单独分享实验证据时保留 manifest、24 组原始日志和 CSV，并注意绝对路径；不要把合成测试输出当成正式结果。
