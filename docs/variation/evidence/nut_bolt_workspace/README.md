# Nut & Bolt 操作路径与位置采样

覆盖三个注册的单臂 Sharpa 短任务。从原位置 PR 的 `c5dc336` 独立开发，实测源码为 `a154fa33e5da8a963ee7f2b1835b76cfe96fc9ff`。普通构造、旧显式布局及 Long 原生阶段继续使用原入口。[原位置范围与旧样点](../nut_bolt_position_boundaries/README.md) · [采样表](../../../../tasks/nut_bolt/workspace_cells.json) · [独立采样器](../../../../tasks/nut_bolt/workspace.py)

## 变量与边界

桌面以各环境自身的世界坐标表示。+X 朝桌内，+Z 朝上，XY 公共输入为绝对米，正偏航从上方看为逆时针。新模式按有效朝向等概率抽样，再在该朝向已筛选的等体积单元内连续抽样。同一单元只计一次。图中旧域、标称值和原生交接区可与旧 PR 对照。边界是对应网格和操作模型的计算结果。

| 场景 | 可变化的量、随动物与交接 | 样点和边界图 |
|---|---|---|
| PickBolt | 左手拾取水平杆。按螺栓根 XY、杆轴方向解两侧进入、提起、持物翻正、移向原生成功盘和放下。六角头沿用原 PR 的平面着桌、几何支撑高度。可抽 30°、60°、75°、90°。尝试的其余角度保留原生或旧显式入口适用的部分。 | 同为 60°，`near`、`far` 的实测根 X 相隔 11 cm，Y 相同。重新翻正后观察是否稳定放下并锁定。[位置](PickBolt_xy.png) · [杆轴](PickBolt_yaw.png) |
| SeatNut | 右手取自由螺母。联合域的四维坐标为锁定螺栓 XY、螺母相对它的 XY。按完整六角头在成功盘内、螺母与承托盘净距、双指取件和沿轴下放筛选。原生锁定实体、承托盘和隐藏的 revolute 表示随阶段初始化。 | 固定同一螺栓轴位，两预设从约 18.06 cm 和 28.02 cm 处取母。同一回合从两侧夹起后观察下放窗口。[轴位](SeatNut_xy.png) · [自由母位](SeatNut_free.png) |
| TurnNut | 右手转已就位螺母。轴位和相对关节角共同决定可进入的面。离线按每段 60°、换面后继续的三段逆时针路线检查到 π，累计进度由原生阶段从零开始。 | 两预设起角均为 0°，同 Y 轴位的 X 相隔 9 cm。试在第一次换面后恢复有效接触。[轴位](TurnNut_xy.png) · [初始转角](TurnNut_yaw.png) |

## 筛选的物理含义

从真实 CPU reset 导出七个关节的世界轴、实际限位、开手双指位置、手腕／掌体／支架网格方位见证点和实体碰撞几何。离线求解采用前一步姿态初始化下一步。拾栓抓取后绑定一个随手转动的杆轴见证点，以约束翻正姿态。套母按已测原生高度生成取件、抬高、转移、同轴下放和退出路径。旋母按对侧六角方向试不同进手面。在关节插值点检查掌部见证点距桌面和直立螺栓／平台柱体的净空，并以肘腕关节附近包络粗查桌边。记录每个候选的首个筛除原因及阶段。[原生模型快照](model.json) · [编译器与门槛](../../../../tools/variation/nut_bolt_workspace/screen.py) · [任务路径](../../../../tools/variation/nut_bolt_workspace/routes.py) · [逐格分类](screen.csv)

拾栓和旋母先以 20 mm 格发现区域，再将有通过点的格细分至 10 mm。套母使用 30 mm 的四维联合格。每格须有同一条路线通过全部角点、中心和一个内部点。编译后另用一个偏离对角线的格内点审计。PickBolt、SeatNut、TurnNut 分别保存 660、144、250 个位置单元。拾栓筛出的四个角度之外，部分旧点仍可通过 `position_layout` 定点试用。套母候选有 48 个四维单元因六角头成功盘或其他静态约束被筛除。旋母有 55 个细格在已试路线中出现过大关节跳变。搜索框外、格间连续碰撞、手指合拢后的受力和真实换抓还需独立判断。双指开手间距提供可达性近似，短动作结果另列。

下表按候选框计算各朝向的通过面积之和，套母用四维体积。最后一列给出一次随机 reset 落入某一个近端或远端预设所在单元的概率，命名调用直接取对应中心。路线角度见逐格 CSV。

| 任务 | 各朝向的有效单元 | 候选框保留份额 | 近／远各自单元概率 |
|---|---|---:|---:|
| PickBolt | 30° 有 156 格，60°、75°、90° 各 168 格 | 49.11% | 0.149% |
| SeatNut | 144 个联合格，90°、150° 进手路线各支持 72 格 | 75.00% | 0.694% |
| TurnNut | −20°、0°、20° 分别有 33、85、132 格 | 57.87% | 0.392% |

另按每格角点和中心复算假设夹持后的运动体扫掠，空间及转角相邻样点最多相隔 5 mm、5°。拾栓使用完整六角头及 21 块原生圆柱碰撞体，翻正与落盘时的最近桌边余量约 67.86 mm。套母和旋母使用六个实际壁块，与螺栓圆柱包络最小间隙约 1.05 mm，承托面的预期接触另计。几何回算以物体跟随理想夹持为条件。[逐角度扫掠结果](held_geometry.json) · [复算程序](../../../../tools/variation/nut_bolt_workspace/held_geometry.py)

## 调用与复现

```python
import gymnasium as gym
import tasks

env = gym.make("NutBoltSeatNut-Sharpa-v1", position_workspace=True,
               num_envs=1, sim_backend="physx_cpu", control_mode="pd_joint_pos",
               obs_mode="state", render_mode=None, reconfiguration_freq=0)
env.reset(seed=930)
env.reset()  # 同一环境的下一次随机布局
env.reset(options={"workspace_placement": {"0": "near"}})
row = env.unwrapped.get_position_workspace_records()[0]["layout"]
env.reset(options={"workspace_placement": {"0": row}})
env.close()
```

数值行须提供该任务的全部旧字段，具体布局须落在一个联合有效格内。旧 `position_layout` 保留旧边界与缺省字段。固定请求及状态恢复不推进位置序列。显式全量 seed 重新初始化序列。局部 reset 省略 seed，选中环境按原契约以严格递增索引给出。选区、所有数值和外观覆盖经过预校验后才写入。本轮样点先按 CSV 的 seed 完整 reset，再提交该行指定的 reset。命名预设和数值回放均适用。

## 验证与复核

原生 CPU 三项共 67 个合法初态、15 个原子拒绝和 17 个支撑／固定根观察通过。全量同 seed 重播、无 seed 推进、插入固定请求、纯状态恢复和原 PR 显式标称与默认构造对照通过。各任务另精确重播 8,192 次离线抽样。3 个任务各测旧标称、新近端与新远端，共执行 9 次原生短动作。未出现达到门槛的同帧双指接触，完整机器人成功与人工手感待试用。近、远六个新预设的初始三段双指 IK 均在旧 15 mm 审验尺度内。[CPU 清单和 Long 四阶段回读](cpu/manifest.json) · [拾栓逐点](cpu/PickBolt.csv) · [套母逐点](cpu/SeatNut.csv) · [旋母逐点](cpu/TurnNut.csv)

Windows 和 Linux 各用两个真实物理环境，依次只重置 0 或 1。两平台分别实测 67/67 个合法点和未选侧隔离，覆盖位置、速度、固定／交接状态、机器人关节、控制目标与各随机序列。每个平台另通过 21 个冲突／非法请求的原子拒绝和 17 项支撑／固定根检查。各自执行 9 次短动作，合格接触与动作 0/9，原生成功 0/9。六个近／远预设在三个后端的三段双指 IK 都在 15 mm 内，最大残差来自旋母近端，在 Windows 为 13.64 mm、Linux 为 13.74 mm。旧标称拾栓在三个后端均超过 39 mm，旧标称套母在两个 CUDA 后端约 49.81 mm。

| 双环境设备 | 身份与运行元数据 | 逐点 CSV |
|---|---|---|
| Windows RTX 4070 Laptop | wininterop7，195.81 s，最低剩余显存 5,515 MiB。启动器核验加载的 DLL、Python、系统 Vulkan 和两项原生补丁。[输入清单](cuda/manifest.json) · [SDK 回执](cuda/nut-cuda-v1-receipt.json) | [拾栓](cuda/PickBolt.csv) · [套母](cuda/SeatNut.csv) · [旋母](cuda/TurnNut.csv) |
| Server3 Linux A800 | Slurm 142368，Nut 专用 linuxnut1 wheel、PhysX 5.3.1 及两项原生补丁。18 个源码文件的 SHA256 均与受测提交的 Git 对象一致。[输入清单](linux_cuda/manifest.json) · [SDK、设备与逐任务计数](linux_cuda/receipt.json) | [拾栓](linux_cuda/PickBolt.csv) · [套母](linux_cuda/SeatNut.csv) · [旋母](linux_cuda/TurnNut.csv) |

用相同的 12 个预登记种子分别测试原生布局、旧显式域内参考抽样及新模式。下表是 CPU 实际 reset 的 10%–90% 分位区间，单位 cm。PickBolt、TurnNut 比较螺栓根 X，SeatNut 比较螺母到锁定轴的平面距离。实际抽样频数、逐次 reset 耗时和动作轨迹都在原始 JSON 中。三个分布的参考种子相同，受测区间有交叠。新的固定预设可以直接复现指定差异。[拾栓原始记录](cpu/PickBolt.json) · [套母原始记录](cpu/SeatNut.json) · [旋母原始记录](cpu/TurnNut.json)

沿原 PR 的真实 CPU 检查器重放 44 个合法点和 6 个越界点，所有行的状态读回、支撑、IK 和拒绝信息与旧结果逐值相同。六次重新建场对照验证了外观切换与位置序列独立。对新域每个朝向和坐标轴的正负端又实测 36 对“边界接受、向外 10 µm 拒绝”，逐对核对物理、任务状态、控制器目标和位置序列。[旧点对照、外观与边界复测](cpu/legacy_comparison.json)

| 场景 | 原生 | 旧显式参考抽样 | 新路径抽样 |
|---|---:|---:|---:|
| PickBolt | −28.18 ～ −21.49 | −29.43 ～ −19.52 | −27.69 ～ −20.64 |
| SeatNut | 19.07 ～ 28.34 | 17.41 ～ 28.64 | 20.60 ～ 28.88 |
| TurnNut | −18.13 ～ −11.44 | −16.75 ～ −6.13 | −16.67 ～ −10.30 |

同 12 个种子的原生／旧显式／新模式 CPU reset 耗时中位数分别为 PickBolt 5.37／5.74／5.34 ms，SeatNut 5.88／5.83／5.99 ms，TurnNut 5.89／6.00／6.16 ms。各小样本只描述本次机器运行。

在仓库根目录可重建模型和格表。模型采集与运行检查使用原生 DexArena 环境，离线编译另需 Numba，绘图使用 Matplotlib。检查器将样点、实测姿态、命名与数值请求、组合角点、接触、错误及源文件身份写入新的输出目录。

```text
python -B tools/variation/nut_bolt_workspace/capture.py
python -B tools/variation/nut_bolt_workspace/screen.py
python -B tools/variation/nut_bolt_workspace/held_geometry.py
python -B tools/variation/nut_bolt_workspace/check.py --sim-backend physx_cpu --output outputs/nut_workspace_cpu
python -B tools/variation/nut_bolt_workspace/figures.py outputs/nut_workspace_cpu
```

Windows CUDA 使用原 Nut 私有 SDK 启动器，将 `--checker` 指向 `tools/variation/nut_bolt_workspace/check.py`，传 `--sim-backend physx_cuda`。Linux 在已加载匹配私有 wheel 的环境中可直接使用同一检查器和后端参数。可加 `--task PickBolt`、`SeatNut` 或 `TurnNut` 隔离为单任务进程。GPU 入口显式核对 indexed apply 和原生锁同步版本。[SDK 使用说明](../../../../tools/variation/sapien_sdk/native_lock/README.md)

## 2026-11-27 双环境复核

三项注册任务分别在位置分支 `582a8a7` 及其与 `main@00cc8e0` 的集成树 `0a92509` 上实测。Windows PhysX CUDA 双环境、seed 717。先取两行 far 对照，再将两行初始化为 near；随后依次仅将 env1、env0 reset 至 far，局部调用省略 seed。六个方向的未选行位姿逐分量完全相同，所选行与同一物理环境的全量 far 对照满足 1×10⁻⁵ 分量误差门槛。两个版本的双向读数一致。索引逐任务保留两行操作前后实值、四元数、构造和 reset 参数、受测树、启动命令及 SDK 的原件入口。

还逐一将 1,054 个已编译格中心送入本家族数值回放入口，并检查全部命名预设。位置接口和既有行为通过 57 项家族测试。 [逐行位姿、实际构造参数及原件索引](paired-reset-20261127.json)
