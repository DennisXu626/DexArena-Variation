# PR30-R4：Meal 局部 reset 活动目标隔离返修

## 目标与改动

- 上轮问题：只 reset env0，未选 env1 的 Franka 活动目标从 -0.625 rad 变为当前位置 -0.500 rad；画面不变不能证明控制目标隔离。
- 本轮基于 PR head `01468f2451a3d2f41cef08a8d7aad5bc574f56b8`，PR 原 base 为 `58de243f4ba7f09865b3f2cd7d7b65d1b1cb26ed`；目标 main 核对为 `399f3e41eba08bbab3cb0ff14cf5a5e95883a8e9`。没有将目标 main 合入本轮受测工作树；实际受测源码字节身份见 [metadata.json](metadata.json)。送审 head 为包含本文件的修复提交，PR 正文另列完整 SHA。
- 修复位于 `tasks/meal_preparation/meal_preparation_long.py` 的 `MealPreparationBase.reset/get_info`：对局部 reset 保存未选行的 Franka 活动目标，在 `get_info` 调用 evaluate 之前恢复，并在异常或正常退出时清理保护。参照 #31 Package 已有修复，未改公共 SDK、共享控制器、物理、成功条件或配色。
- 四个 Meal 入口继承同一保护，全量 reset 继续委托原实现。应用方式不变：`env.reset(options={"env_idx": [0], ...})`；反向用 `[1]`。真实 original/variant 选项继续沿用既有外观配置。

## 实际验证

本轮只运行 Windows CPU 源码级回归，Python/Torch/NumPy 版本、命令、退出码及源文件 SHA-256 见 [metadata.json](metadata.json)。使用仓库内冻结的 ManiSkill 3.0.0b22 reset/action 方法及生产 Franka reset/set_action、Meal reset/get_info/_initialize_episode。场景 I/O、初始化机器人位置、外观记录、evaluate/get_obs 回调为测试替身；没有创建真实机器人或 PhysX 场景。无 GPU 作业、无新增 GPU 分配。

| 验了什么／状态 | 实际受测版本与条件 | 判据与实际结果 | 原始证据入口 |
|---|---|---|---|
| Meal 源码级回归：通过，5 项 unittest | metadata 中源码哈希，CPU、2 行；四入口各 env0/env1 两方向 | 旧实现八方向均被隔离断言检出；修复后 evaluate/get_obs 入口、出口及返回时未选行目标保持；选中行重新初始化。另覆盖全量 reset、关闭外观、嵌套控制器字典、未初始化目标、异常清理 | [测试输出](test_meal_partial_reset.txt)、[逐行目标](targets.json) |
| Package 既有回归：通过，4 项 unittest | 同一工作树，CPU | 既有 Package 反例、全量 reset 和异常清理无退化 | [测试输出](test_package_partial_reset.txt) |
| 共享 row_state：通过，2 项 unittest | 同一工作树，CPU | Meal/Package 两套 checker 保持既有输出 | [测试输出](test_shared_row_state.txt) |

最小复现命令（仓库根目录）：

```console
python -m unittest discover -s tests -p test_meal_partial_reset.py -v
python tests/test_meal_partial_reset.py --evidence
```

首关节位置两行均为 -0.500 rad；通过动作接口设置左臂目标 env0=-0.375、env1=-0.625 rad，右臂为 -0.250、-0.750 rad。省略 seed 局部 reset。`targets.json` 逐一记录选中行、未选行、四个回调边界及返回实值。例：open/selected0 的旧实现 env1 左臂变为 -0.500，修复后全程 -0.625；selected1 的未选 env0 全程 -0.375。测试替身中的 original 记录检查只验证初始化转发，不代表真实材质恢复或配色验收。

## 剩余问题与返修交接

- GPU 未复测。本轮八方向仅为 CPU 调用链回归，不能替代八方向真实 PhysX CUDA 独立验收。上轮 Server3 作业 143923 仅一个方向失败，其余七个未到达；本轮没有改写其状态。
- 请独立执行层在新 head 上先复测 OpenLunchBox selected0 原反例；通过后继续四入口双向共八方向、真实 evaluate/get_obs 边界目标、original 恢复、完整材质及同号配色断言。新 GPU 作业按反馈单独申请范围和预算。
- 历史贴图、原帧、资产检查继续复用，不重新渲染。作者原帧入口 `/data/home/pb/paired-full-20261121/results-125331/meal/`，团队读取账号 `xkl`，索引 PR30_files.csv 的 260 条 PNG SHA-256 已逐项匹配；权限已配置，等待读取方实读。本地先前没有成功切换为 xkl，不能声称该身份已实读。
- 上轮独立审验原证据入口 `/mnt/ceph2/xkl/DexArena/pr_review/PR30-R4/run_01/recovery_01/`；其中 `capture/open/selected_0/result.json` 为原失败实值。该历史 GPU 证据不作为新 head 已通过的证明。

归档补充：CPU 受测生产/测试源码对应提交 `a83a0668848367c9448501c32c580f61612cb724`。后续归档提交仅修改本 README 和 metadata.json，记录 Windows 工作树 CRLF 与 Git blob LF 的两组 SHA-256；逐文件已验证仅有换行差异，生产代码、测试及 SDK 夹具均未改动。最终送审 head 以 PR 正文为准。
