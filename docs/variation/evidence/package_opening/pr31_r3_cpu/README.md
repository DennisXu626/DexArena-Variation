# PR31-R3：有动作命令时的局部 reset 隔离修复

返修针对 head `da6617502ee0f5032cfacfeedb97b169172afd9e`。R1 的控制目标采样缺口已关闭；R3 指出真实 reset 行为会丢失未选行命令。本次先完整读取返修说明、CPU 探针、六条反例、历史证据审计及日志，再复现、修改。

## 原因与修复

ManiSkill b22 在选中行初始化后将 `scene._reset_mask` 设为全行，再执行组合控制器 reset。Franka 阻抗控制器因此把未选行 `_target_qpos` 也写成当前 qpos。原60例检查没有预先发送不同命令，两个环境的目标恰好等于复位 qpos，差值为0不能证明动作目标隔离。

生产修改仅在 `PackageOpeningLongEnv`（两个短入口继承）增加公开 reset 与 get_info 保护：局部 reset 前保存未选行的实际手臂目标；在 BaseEnv 组装 info/obs 前恢复，reset 退出时再次恢复并清理临时保护。选中行由原逻辑处理，未指定 env_idx 和显式全选继续直接调用原全量 reset。共享 Franka 控制器、SDK、其它任务不改。

Package A5 在候选和 native 全量 reset 后发送相同动作，两行首关节使用不同合法目标；显式断言两行目标不同，且各自偏离当前 qpos 超过0.01 rad。动作经过 agent、组合控制器和各子控制器正式 set_action 路径，不执行物理步。局部 reset 前后仍保存实际目标与原始相机图；每例另保存命令。Meal 分支保持原 reset/capture 顺序。

## CPU 结果

|入口|旧公开 reset 路径|修复后的公开 reset|info/obs读取时|选中行与全量 reset|
|---|---|---|---|---|
|OpenPackage 双臂|双向失败|双向通过|未选命令保持|与旧路径相同|
|ExtractApple 单臂|双向失败|双向通过|未选命令保持|与旧路径相同|
|Long 双臂|双向失败|双向通过|未选命令保持|与旧路径相同|

首关节物理位置固定为 −0.5 rad。reset env0 时未选 env1 的命令 −0.625：旧实现返回 −0.5，修复后仍为 −0.625；反方向未选 env0 的 −0.375：旧实现返回 −0.5，修复后仍为 −0.375。步数分别保持5与3。完整向量、hand后端值及返回 obs/info 见 [behavioral_witness.jsonl](behavioral_witness.jsonl)，修后六行单列在 [after.jsonl](after.jsonl)。

修前先在未修改的 `da66175` 工作树执行返修原探针，六行全部 isolated=false，原始 stdout 为 [before.jsonl](before.jsonl)。随后行为测试调用新增的 Package reset/get_info 实现；以同一任务初始化和 b22 BaseEnv.reset 作为 legacy 对照，同一正式 A5 比较器在旧路径失败、修复后通过。不会绕开新 override 后将结果冒充修复通过。

手部检查使用 b22 PDJointPosController 的真实 set_action/reset/set_drive_targets 方法；替身 articulation 后端独立保存非零 drive targets/velocities。reset 中后端写入次数未增加，未选行两类值保持。源码亦表明该 PD reset 只更新内部缓冲，不调用 drive setter。因此本轮只保护证实受影响的阻抗手臂目标；不宣称验证了真实 GPU 手部动力学。

本地和 Server 3 ms3 的8项CPU回归均通过，覆盖原采样反例、动作前置断言、三入口双向 reset、obs/info、选中行一致性、全量 reset及异常清理。完整输出见 [cpu-tests.txt](cpu-tests.txt) 和 [cpu-tests-server3.txt](cpu-tests-server3.txt)。两处 NumPy2 环境对 b22 agent 的 np.isnan(torch_tensor) 发出弃用警告，测试通过；保留原SDK方法未改。

## 复现

在仓库根目录（NumPy、CPU Torch）：

```text
python -B -m unittest discover -s tests -p "test_package*.py" -v
python -B tests/test_package_partial_reset.py --evidence
```

第二条命令输出旧路径六行和修复路径六行，隔离测试检查两者分别失败／通过。测试从仓库生产代码提取实际方法，加载 [b22方法片段](../../../../../tests/fixtures/package_b22_reset.py)，无需导入SAPIEN或初始化GPU。片段保留 upstream reset/action 方法体；SDK原文件身份见 [sdk_source_hashes.json](sdk_source_hashes.json)，方法体逐项AST核对见 sdk_fixture_audit.json。物理、力矩应用、布局、观测采样为替身；CPU探针不是完整仿真。

复现修前原反例：检出 `da66175`，执行以下命令，其中 SDK目录为 Server 3 的 `.../site-packages/mani_skill` 或字节相同的源码副本：

```text
python -B original_review_probe.py <da66175检出根目录> <mani_skill源码目录>
```

[original_review_probe.py](original_review_probe.py) 原样保留返修探针；它遇到新增 reset 会拒绝继续，修后应使用上面的正式回归。

## 范围与交回

本轮 Slurm提交0次、GPU运行0次。真实双环境GPU独立复核按返修要求交团队执行层安排。旧33对四步轨迹、配色原图和历史日志保留；旧60/60只描述初态附近、目标等于qpos时的历史检查，不能继续作为活动命令隔离的验收结论。R3结果为CPU源码级行为回归通过，未宣称GPU复验或完整任务成功率通过。
