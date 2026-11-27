# Pipette Transfer 工作空间与遥操前实测

AspirateLiquid 用右手从支架取管、移到样品皿后归还。DispenseLiquid 用左手取管、移到架中试管后归还。Long 在一张桌面上给两只手选同一个停放位。三者在各自注册的 Sharpa 机器人上建立位置表，在线 reset 只采表和计算连续坐标。

## 算法与入口

1. 在原生 CPU 场景读取桌面、支架、皿、架、试管、移液器、机械臂七个关节的世界轴线与限位，以及拇指、食指和手掌的位置。把支架和目标物成对放在 10 mm 网格上，对每种支架角度剔除桌边、支架与容器净距不足的格子。
2. 以两个接近方向追踪 11 个位姿，从原生手位抵达管身、沿支架上提、越过实体顶部，再垂直下降到皿口或试管口；归还沿相同路段逆行。筛选双指误差、步间关节变化、腕掌高度与支架后壁余量。Long 的每条单手路线还检查另一只手停在原位时的距离，并逐一复算支架与容器四个坐标的 16 个顶点，最后在共同支架位置连接两手的可行单元。[构建器](../../../../tools/variation/build_pipette_workspace.py) · [求解器](../../../../tools/variation/pipette_workspace_motion.py) · [实测几何与筛选计数](BUILD.json)
3. 每次随机 reset 先等概率选支架角度，再等概率选该角度下一个等体积的联合单元，最后在格内连续取点。工作站 X、Y 为世界坐标，单位米，角度绕世界 +Z，以度计。固定请求按完整联合坐标验证。每个环境独立维护随机序列，固定布局和状态恢复可插入序列，回报记录 seed、环境号、抽样序号和实际布局。[运行时位置表](../../../../tasks/pipette_transfer/workspace_cells.json) · [采样与数值回放](../../../../tasks/pipette_transfer/position_workspace.py)

| 任务 | 78° 格数 | 90° 格数 | 102° 格数 | 本次独立复算的不同顶点 |
|---|---:|---:|---:|---:|
| AspirateLiquid | 429 | 429 | 572 | 766/766 |
| DispenseLiquid | 1,287 | 1,287 | 1,287 | 815/815 |
| Long | 927 | 2,277 | 4,068 | 3,512/3,512 |

Short 的手指目标给格中心残差加上格半对角裕量。顶点抽查混合各坐标的正负边界，覆盖极值格及固定种子的留出格。两指 15 mm 是运动学筛查容差，管口对准、有效握持、按压和液量仍以原生物理与任务判据为准。Long 的两条路径按顺序执行。[逐顶点结果](CELL_VERTICES.json)

```python
import gymnasium as gym
import tasks

env = gym.make("PipetteTransferAspirateLiquid-Sharpa-v1", position_workspace=True)
_, info = env.reset(seed=88301)
record = info["workspace_placement"]
env.reset(options={"workspace_placement": {"0": "near"}})
env.reset(options={"workspace_placement": record})
env.close()
```

预设为 center、near、far、left、right。在 90°、两个短任务上，near 到 far 的取管点向 +X 移动 12 cm；right 到 left 向 +Y 移动 10 cm。显式数值请求须给支架 XY、支架朝向和任务内所有容器 XY。关掉位置工作空间即可走原生采样；原 PR 的 position_layout 接受原来的字段和边界。[旧布局与边界](../pipette_position_boundaries/README.md)

## CPU 实测

在 3a1593a 的三个注册任务上，分别以相同的 12 个 seed 实测原生、旧布局和新采样三组 reset，再实测 5 个预设、12 个定向边界和 3 个边界外点。共记录 159 个合法初态及 9 个边界拒绝，另有模式冲突和状态恢复检查。三组机器人初始关节逐 seed 相等。每任务还复现 8,192 次采样。[逐点 CSV](cpu/POINTS.csv) · [版本、分位数与完整回执](cpu/RESULTS.json)

| 任务 | 粗略 IK 通过数，原生 / 旧布局 / 新采样（各 12） | 新采样支架 X 的 P05–P95 | Y 的 P05–P95 | 新采样 reset 中位耗时 |
|---|---|---|---|---:|
| AspirateLiquid | 12 / 12 / 12 | −22.8 至 −12.1 cm | −19.3 至 −11.8 cm | 4.8 ms |
| DispenseLiquid | 12 / 12 / 12 | −22.8 至 −12.1 cm | −19.3 至 −11.8 cm | 5.2 ms |
| Long | 12 / 10 / 12 | −22.3 至 −11.9 cm | −21.0 至 −13.1 cm | 6.8 ms |

三个任务的 center、far 共六次松手支撑通过。两个短任务在这两点共跑四次 72 步取管，末帧均未达到 25 mm 的稳定抬升门槛。遥操可先在 center 建立管身双指接触，再试 far 的提管、管口对准、按压和归还；Long 还要验证同一停放位上的换手、阶段推进与最终液量。逐点表保留接触力、抬升和任务成功字段。

## 双环境 CUDA

Windows RTX 4070 Laptop 以同一提交 3a1593a、正式 indexed-apply SDK 运行两个环境。三个任务合计 159 个合法初态、9 个几何拒绝，另测整批第二行非法、模式冲突、种子序列及状态恢复。逐点表记录 60 个受保护环境摘要对照；每个入口通过 143 个检查。六次支撑观察通过，四次短动作的终帧都未稳定抬起管身。[Windows 逐点数据](cuda/POINTS.csv) · [任务回执](cuda/RESULTS.json) · [SDK 身份](cuda/private_sdk.json)

Server 3 的 A800 40 GB 在作业 142368 中以同一提交、正式 Linux SDK 和两个环境完成三个入口。159 个合法初态、9 个几何拒绝、60 个受保护环境摘要以及每入口 143 个检查均符合预期。三个入口各 12 次新采样均满足运动学路线检查，六次支撑观察通过。两项短任务的 center 和 far 共四次均未达到稳定抬升门槛。[Linux 逐点数据](linux-cuda/POINTS.csv) · [任务回执](linux-cuda/RESULTS.json) · [上机代码及 SDK 身份](linux-cuda/pipette-sdk.json)

## 边界与复现

图中浅蓝色是容器可随动时的投影，深蓝色是把其余物体锁在 center 时的切片。图同时给出桌面、机器人、同一方向物及实测余量；完整坐标可从 CSV 的 request 和 actual 复现。[支架 XY](stand-xy.png) · [支架朝向](stand-yaw.png) · [样品皿 XY](cup-xy.png) · [试管架 XY](rack-xy.png)

从本家族工作树运行以下入口。CUDA 使用该平台的 indexed-apply 私有 SDK，两个环境在同一设备上分别做局部 reset。output 指向新目录。

```shell
python -B tools/variation/build_pipette_workspace.py --audit docs/variation/evidence/pipette_workspace/BUILD.json
python -B tools/variation/audit_pipette_cells.py
python -B tools/variation/check_pipette_workspace.py --sim-backend physx_cpu --output /path/to/new/cpu
python -B tools/variation/check_pipette_workspace.py --sim-backend physx_cuda --output /path/to/new/cuda
python -B tools/variation/plot_pipette_workspace.py
```

## 2026-11-27 双环境复核

三项注册任务分别在位置分支 `7bf212b` 及其与 `main@00cc8e0` 的集成树 `f561651` 上实测。Windows PhysX CUDA 双环境、seed 717。先取两行 far 对照，再将两行初始化为 near；随后依次仅将 env1、env0 reset 至 far，局部调用省略 seed。六个方向的未选行位姿逐分量完全相同，所选行与同一物理环境的全量 far 对照满足 1×10⁻⁵ 分量误差门槛。两个版本的双向读数一致。索引逐任务保留两行操作前后实值、四元数、构造和 reset 参数、受测树、启动命令及 SDK 的原件入口。

还逐一将 12,563 个已编译格中心送入本家族数值回放入口，并检查全部命名预设。位置接口和既有行为通过 25 项家族测试。旧显式布局及工作区均用超出 float 表示范围的整数复现了异常类别错误，修后两个入口均返回 ValueError。 [逐行位姿、实际构造参数及原件索引](paired-reset-20261127.json)
