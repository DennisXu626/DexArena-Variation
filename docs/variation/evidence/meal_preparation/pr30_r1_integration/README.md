# PR30-R1：同步已合入PR31的main并统一检查器

原PR30 head为 `049bca9a93a343a50efaf0286e2af247d3e3e9d7`；本次合入的 `origin/main` 为 `58de243f4ba7f09865b3f2cd7d7b65d1b1cb26ed`，包含PR31合并提交 `035b69c` 及其后文档更新。

## 处理

实际集成出现两处add/add冲突：`check_ten_environment.py` 与 `check_ten_environment_paired.py`。普通检查器差异是Package带环境行后缀的actor筛选；paired检查器还包含PR31后续验收的控制目标采样、区分性动作前置条件和A5比较。本次逐项核对后，两份脚本完整保留main版本，未回退Package修复。Meal的生产任务、配方和catalog与原PR30相同。

新增 `tests/test_shared_row_state.py` 从实际脚本提取plain/row_state：用同时包含box_0/1、procedural_box_0/1、partnet_box_0/1、package_0/1及双环境机器人张量的状态，验证两个方向的Package行筛选；Meal逐项对照原PR30实际函数，验证保留无前缀键、只过滤相应按行实例，并验证快照不被原张量后续修改污染。

## 验证与证据身份

- 2项双家族行筛选回归通过；继承main的8项Package回归通过。
- `check_static.py`、`check_appearance_archive.py` 均通过。完整命令和退出码在 [integration.json](integration.json)，原始输出为同目录txt。
- [integration.json](integration.json) 逐文件保存历史实际执行源码SHA-256、原PR30 Git字节SHA、集成后LF源码SHA和明确的LF/CRLF匹配类型。8个Meal生产／catalog路径内容未变，且与历史执行源清单相符。
- 历史实际执行的paired检查器保留其原SHA；集成后检查器已改变，两个SHA都记录，不把历史运行冒充新检查器的GPU结果。Meal行筛选等效由本轮CPU回归验证。
- 历史四入口44行A4、80例初态附近A5及随机序列结果保留在 [历史报告](../paired_revalidation/README.md)，本轮GPU运行0次。贝果1、2号仍使用原PR30的新烘焙配方，未恢复旧两套。

本轮未修改Meal控制器或reset，也未证明持有不同活动命令时的Meal隔离；不将PR31的Package专用行为修复直接推广到Meal。独立Server3编号／配色检查仍由审验层按其流程安排；历史实景和本轮CPU检查不替代该步骤。完整机器人成功率未测。
