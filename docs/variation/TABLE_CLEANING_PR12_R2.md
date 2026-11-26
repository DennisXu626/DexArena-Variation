# Table Cleaning PR12 R2 reset 隔离修复

基线为 PR #12 的 `753b96e04f3cd545339f019498a430eaaf9b03cd`。
本次只修改三个 Sharpa 入口共用的 `TableCleanBase`，没有改配色、素材或共享机器人控制器。

## 行为

- 无 seed 的局部 reset：保留未选环境的阶段、hold、成功标记、阶段标记、碎屑位置历史及控制器逐环境张量缓冲（包括真实阻抗目标）。
- 在基类 `get_info()` 前恢复未选行控制器和任务状态，在其评估结束后再次恢复任务状态，随后才生成策略观测；最终清理使用 `finally`，也覆盖异常路径。
- 局部显式 seed 在进入 BaseEnv 前抛出 ValueError；全量显式 seed 继续调用原有基类路径。外观非法 ID 的原有前置校验保留。

## CPU 验证

使用 Python 3.13、CPU Torch 2.6.0 和 ManiSkill 3.0.0b22 wheel。
未安装或启动物理仿真器；通过 AST 加载该 wheel 的真实 BaseEnv.reset、RNG、get_info、get_obs、BatchedRNG，仓库真实阻抗控制器 reset、PickDebris.evaluate 和碎屑历史逻辑。物理、接触、位姿及场景初始化由 CPU 替身提供。
外观验证另由现有真实 selector/material CPU 检查覆盖，新隔离测试只借用其 selector 和材质替身。

```text
python -B tools/variation/check_table_cleaning_isolation_cpu.py --mani-skill-wheel <mani_skill-3.0.0b22-py3-none-any.whl> --output docs/variation/evidence/table_cleaning/r2_isolation_cpu.json
python -B tools/variation/check_table_cleaning_isolation_cpu.py --mani-skill-wheel <mani_skill-3.0.0b22-py3-none-any.whl> --revision 753b96e --output docs/variation/evidence/table_cleaning/r2_old_counterexamples_cpu.json
```

修复版 4 项测试通过；旧 head 同样的正向断言失败 17 个子用例（预期退出码 1），涵盖三个原反例和异常清理。结构化输出保留目标值、返回阶段、内部阶段和设种前后下一次随机采样。
覆盖两个重置方向、外观开关、enhanced determinism 开关、选中行初始化与观测、全量设种、拒绝请求无 RNG/控制目标/阶段/步数副作用，以及后续时间边界阶段仍可推进。后续时间边界由替身推进计数，不能视为真实物理步进证据。

其余检查：

- `check_table_cleaning_reset_cpu.py`：11 项通过。
- `check_table_cleaning_single_env_cpu.py`：64 组通过，最大差 0。
- `check_table_cleaning_preview_cpu.py`：8 项视图/方案记录通过。
- `check_static.py` 及 `git diff --check`：通过。
- `check_appearance_archive.py`：当前 CRLF 工作区在既有 catalog 字节哈希处失败；核对 Git blob 与记录哈希相等后，以 `git -c core.autocrlf=false archive --format=zip HEAD` 导出临时 LF 副本并覆盖本次源码，原检查通过（42 对象、13 PNG、318 相对链接）。没有修改 Git 换行配置或历史证据。

本次没有 GPU 作业、渲染、远程执行、推送或合并。三个任务共用 reset 的集成行为、真实 GPU 物理与实际配色仍需后续执行层验证；阶段边界 CPU 反例具体覆盖 PickDebris，不宣称另外两个任务已完成仿真实测。
