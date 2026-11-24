# Pipette Transfer 运行报告

审验代码 `5e22bee3110491d3221a79b9bfc17c927af3959d`。CUDA 使用 Windows、RTX 4070 Laptop、ManiSkill `3.0.0b22`、SAPIEN `3.0.3+dexarena.gpu1.wininterop5` 和两个并行环境。原生 CPU 使用 SAPIEN `3.0.3` 及一个环境。构造参数、每次 reset 的实测位姿和拒绝原因在 [CUDA 逐点表](POINTS.csv) 及 [CPU 逐点表](cpu/POINTS.csv)。实际 SDK 绑定、文件身份及 CUDA 作业回执见 [平台记录](PLATFORM.json)。

| 入口 | CUDA 初态 | 越界等拒绝 | 释放支撑 | 指尖 IK | 短动作 |
|---|---:|---:|---:|---:|---:|
| AspirateLiquid | 25/25 | 4/4 | 9/9 | 20/25 | 0/2 |
| DispenseLiquid | 24/24 | 3/3 | 9/9 | 24/24 | 0/2 |
| Long 初态与阶段抽查 | 3/3 | 2/2 | — | — | — |

CPU 的初态、拒绝及释放结果与 CUDA 计数一致，两个短任务的开手接近 IK 共 49/49，四次短动作均低于门槛。CUDA 两个方向的局部 reset 共覆盖 52 个合法初态。每行在无物理步进的前后比较未选择环境的 Actor、关节、阶段旗标及步数。九个拒绝点比较了两个环境，状态一致。按同种子比较原生与显式标称的机器人关节起点，两端均逐值一致。

释放观察使用 18 个控制步。移液器吸头在真实底托接触并下沉约 7 mm，试管的原生初始间隙由真实桌面接触闭合。两者保留初始相对工作站关系。吸液 `C-gap`（seed 1544、env0）的净距下界为 20.10 mm。排液 `C-far`（seed 1543、env1）的中央槽壁与试管投影余量为 2.37 mm。两个数值按实测 reset 状态与加载的碰撞形状计算。

IK 保持开手指尖间距，以 15 mm 最大误差检查接近、到达管身、抬过上导向圈及到液体容器上方。GPU 在五个吸液点的接近步骤超过门槛。`stand-xy` 的 `SW`、`NW`、`M`、`SE` 对应约 27.34、41.49、35.30、36.24 mm，`cup-xy / E` 对应约 38.83 mm。`stand-xy / N0` 在两个短任务中均通过。建议遥操作补试吸液 `stand-xy / NW`（seed 1524、env0）的侧向接近。

短动作在两个标称点和两个组合点各执行 72 个控制步，试着合指接触管身并抬升。四次均未达到 25 mm 提升与接触门槛，到吸液、排液及归还的完整操作需遥操作组试用。复现顺序与优先点见[范围与复现](README.md)。

```bash
python tools/variation/check_pipette_positions.py --sim-backend physx_cpu --output outputs/pipette_position_cpu
python tools/variation/plot_pipette_positions.py docs/variation/evidence/pipette_position_boundaries outputs/pipette_position_figures --font <中文字体文件>
```

CUDA 使用 `tools/variation/sapien_sdk/run_task_check.py` 和与 [平台记录](PLATFORM.json) 同一身份的私有 SDK，选择 `--checker tools/variation/check_pipette_positions.py --sim-backend physx_cuda`。CPU 与 CUDA 的初态摘要来自各自记录的运行后端。
