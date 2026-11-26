# PR12-R4 作者返修

起点 head `710f5a059c43d53d65a70d1bc39a3d2b3a260545`，已整合 main `58b54623308ad736f765a8bbccefc74e344f2a3c`。本轮针对 PR12-R4-AUTHOR/AUTHOR_ISSUE.md 的状态恢复回归，未改外观、物理参数、判静阈值或共享控制器。

## 原因与最小修正

修改前原 AUTHOR 探针两个方向均复现：同一步号恢复移动 1 cm 的碎屑，返回 obs/info 计数 3、阶段 1。逐步缓存仅在普通 episode 初始化失效；b22 的 reset_to_env_states 直接调用 set_state_dict，跳过该初始化，错误继承旧状态的静止结果。

set_state_dict 现在在父类恢复完成后，将实际 restore_idx 的运动缓存时间标记设为 -1。首次读取按恢复前位置历史重新计算运动，超过 3 mm 则不计为静止；保留邻居的历史和缓存。放置在 task_state 缺失的提前返回之前，因此无任务字段的物理状态恢复也覆盖。env_idx=None 时覆盖所有恢复行。下一真实步号可继续重新判静。

## CPU 结果

- 原 AUTHOR state_restore_probe.py：两个方向 obs/info 计数均为 0、阶段均为 0。
- 新增 check_table_cleaning_state_restore_cpu.py：由原 AUTHOR 探针扩展，16 组通过。覆盖两个方向、外观开关、直接 set_state_dict／经 reset_to_env_states、存档有无任务字段。验证同帧两次重复读取仍为 0／阶段 0，邻居原有计数 3 及运动缓存/位置历史保持；步号增长后选中行计数 3、阶段 1。
- 原隔离回归 4 项通过，错误 0；原 reset 回归 11 项通过。
- check_static.py、check_appearance_archive.py、git diff --check 通过。

结果：[状态恢复矩阵](evidence/table_cleaning/r4_state_restore.json)、[隔离回归](evidence/table_cleaning/r4_isolation.json)、[AUTHOR 原探针与静态检查输出](evidence/table_cleaning/r4_checks.json)。历史 R3 文件保持原样。

## 复现

```powershell
python -B tools/variation/check_table_cleaning_state_restore_cpu.py <仓库根目录> <b22的mani_skill源码目录> <输出JSON>
python -B tools/variation/check_table_cleaning_isolation_cpu.py --mani-skill-wheel <mani_skill-3.0.0b22-py3-none-any.whl>
python -B tools/variation/check_table_cleaning_reset_cpu.py
python -B tools/variation/check_static.py
python -B tools/variation/check_appearance_archive.py
```

运行使用 CPU Torch 2.6.0、NumPy 和真实 ManiSkill 3.0.0b22 wheel 中 reset/set_state_dict/scene 方法；物理姿态、接触与场景使用 CPU 替身。新增 Server 3 作业 0、GPU 用量 0，不扩展为真实仿真或完整机器人任务验收。
