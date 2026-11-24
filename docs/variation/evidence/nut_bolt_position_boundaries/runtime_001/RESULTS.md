# Nut & Bolt 位置验证与遥操作复现

Windows 双环境 CUDA 覆盖三个 Sharpa 短任务。44 个合法点的位姿、阶段、支撑和未选环境状态均符合预期，6 个越界点均拒绝且状态未变。短动作与粗略 IK 的结果按下表交给遥操作复试。

| 短任务 | 合法初态与静置 | 只 reset env0 / env1 | 越界拒绝 | 双指 IK | 短动作达标 |
|---|---:|---:|---:|---:|---:|
| PickBolt | 13/13 | 7 / 6 | 2/2 | 5/13 | 0/2 |
| SeatNut | 19/19 | 10 / 9 | 2/2 | 18/19 | 0/2 |
| TurnNut | 12/12 | 6 / 6 | 2/2 | 4/12 | 0/2 |

44 次局部 reset 均在物理步推进前比对另一环境的 actor、articulation、任务阶段缓存和步数，逐字段摘要一致。三项同 seed 原生 reset 精确重复，显式布局与原生初始化的机器人初始关节角一致。人工遥操作待试用。

## 采样与判据

圆域覆盖中心和八方，矩形覆盖中心、角点和边中点。离散朝向分别覆盖标称与两端。组合点包含 PickBolt 远端改变杆身方向、SeatNut 螺母和轴位最接近、轴位与螺母同时远移，以及 TurnNut 远端轴位叠加正转角。每个短任务另测两个越界请求。

初始化后从本次实际 actor 和 link 读回四元数、位置、速度与任务阶段。PickBolt 和 SeatNut 用原生碰撞形状核对完整桌面投影，并保持机器人初始关节目标静置 10 个控制步（0.50 s）。记录几何余量、桌面接触、位移和角度差。TurnNut 核对固定根、已激活 revolute 表示、承托面及停放的自由体，静置后记录漂移。静置门槛为位移 ≤20 mm、角度差 ≤20°、支撑面偏差 ≤3 mm，投影不越桌边。两个自由体还要求末步桌面接触力 >0.03 N。

粗略 IK 依次解左手或右手的拇指和食指目标。PickBolt 对杆身测预接近、双指接近与抬起。SeatNut 增加螺栓尖端上方的套入预对准。TurnNut 测已就位螺母两侧及沿轴逆时针 15° 的指向。路径中各目标的最大双指误差须 ≤15 mm。此检查使用原生初始手形与关节限位。短动作使用原生关节位置控制，分别做接近、闭指、抬起或逆时针试转，每阶段 25 个控制步，要求同帧两指各 >0.05 N 并抬起 ≥10 mm 或净转动 ≥8°。按逐点字段保留首次失败处。

SeatNut 最近组合 `S-near` 的平面净距下界为 55.85 mm，静置全组最大位移约 1.00 mm，末步桌面接触力下界约 0.98 N。TurnNut 12 个合法点的固定根 link 在静置快照间无位姿位移。短动作均缺少达门槛的双指接触，`T-far-yaw` 虽读到约 9.27° 的累计转动，仍按短动作未达标记录。

## CPU 对照与纠正记录

Windows 原生 PhysX CPU 输入的 44 个合法请求均通过位姿、阶段和静置核对，6 个越界请求拒绝且状态摘要未变。PickBolt、SeatNut、TurnNut 的 IK 分别通过 7/13、17/19、5/12。共六次短动作执行，均未达到门槛。PickBolt 试放后最大姿态差 4.89°，最小桌边余量 65.01 mm。TurnNut 固定根静置后位姿未漂移。

PickBolt 原生六角头判据另外做了四个构造样点。交接盘中心、其东侧边界内 1 μm 和该东侧边界的浮点实测通过，边界外 1 μm 拒绝。每点都恢复场景并核对同一状态摘要。四个构造样点仅用于判据验证。Long 的四种原生启动阶段、锁定和啮合状态均符合预期，显式请求被拒后状态一致。

首次 CUDA PickBolt 有八个样点超过静置角度门槛，最大滚动约 30.66°，原因是螺栓以棱起始。显式初态改为一个平面朝下，保留原生支撑高度计算。重新 CUDA 运行后，13 个合法点均通过原静置门槛，最大姿态差 4.70°，最小桌边余量 63.11 mm。首次结果保留在原运行目录。

首次 CUDA TurnNut 在 −20° 的零进度读数遇到精度断言。六次零步诊断覆盖两个方向的局部 reset 和全部三档角度。−20° 实测关节角为 −0.3490657806 rad，角速度为零，CUDA 重建 link 四元数后原生读回角度为 −0.3490655720 rad。原生回绕产生 2.384185791 × 10⁻⁷ rad 的残值，未选环境完全一致。检查器允许至多 10⁻⁶ rad 的数值残差，继续核对零仿真步、零轴向深度、实际关节角和位姿。任务本身的累计与成功公式沿用原生实现。

## 复现格式

先试每项标称点，再试表中列出的近侧、远侧或旋转组合。回传任务与样点 ID、动作完成情况、受阻步骤、有效接近侧。

| 任务 | 标称点 | 优先对照的边界与动作 |
|---|---|---|
| PickBolt | `P-XY0` · seed 710 · env0 | `P-XY5` · 715 · env1 是最近桌边点，试从杆身侧面捏取、提起后翻正。再用 `P-near-yaw` · 721 · env1 对照 −90° 朝向，双指粗检通过。 |
| SeatNut | `S-B0` · seed 760 · env0 | `S-near` · 777 · env1 是最紧组合，从自由螺母两侧夹起，移至尖端上方后对轴。再试 `S-far` · 778 · env0 的远角套入，该点双指粗检误差 19.96 mm。 |
| TurnNut | `T-B0` · seed 810 · env0 | `T-far-yaw` · 821 · env1 的 +20° 叠加远侧轴位通过双指粗检。先试夹住螺母外侧并逆时针转动，再对照 `T-Y-20` · 819 · env1，后者最大接近路径误差 72.65 mm。 |

下列调用从 [逐点表](POINTS.csv) 读取任意一个合法初始化行。原版 seed 先用于完整 reset，随后只 reset 该行指定的环境；重复同一顺序可回到同一初态。

Windows 双环境复现使用带原生锁同步和索引写入的 [Nut & Bolt SDK](../../../../../tools/variation/sapien_sdk/native_lock/)。先按 SDK 说明准备本地运行时和原资产，然后用同一 SDK 进程执行下列调用。边界检查器可在同一启动器下以 `--sim-backend physx_cuda --task SeatNut` 重跑单个任务。

```python
import csv
import json
from pathlib import Path

import gymnasium as gym
import tasks

table = Path("docs/variation/evidence/nut_bolt_position_boundaries/runtime_001/POINTS.csv")
with table.open(encoding="utf-8", newline="") as handle:
    row = next(r for r in csv.DictReader(handle) if r["label"] == "S-near")

env = gym.make(row["task"], **json.loads(row["build"]))
env.reset(seed=int(row["seed"]))
obs, info = env.reset(options=json.loads(row["options"]))
# 操作后关闭环境
# env.close()
```

## 原始记录与工具

基线为 `128526c9588098c940b6664372eca8b8eb52aab9`。CPU、PickBolt CUDA 与 SeatNut CUDA 实测提交为 `7a9fd3e27757a14161b1c49b3ccaab48db0b9d70`，TurnNut CUDA 为 `e1c18c31ce3fb38511ca2936c9554e5827d6312b`，两者仅有 TurnNut 检查器的数值容差及读数断言差异。运行依赖为 ManiSkill 3.0.0b22。CUDA 使用 SAPIEN `3.0.3+dexarena.gpu1.wininterop7`，索引写入和原生锁同步能力均为 1。三次正式 CUDA 运行共 241.20 s，最少空闲显存 5846 MiB，均正常退出。逐文件哈希、轮次与数据身份见[环境与用量](RUNTIME_IDENTITY.json)。

边界图的任务点与桌面几何来自 CUDA 采集，整桌图的车体轮廓采用同模型的原生 CPU 碰撞投影。三个任务的 CPU 根坐标回读约为 (−0.87, 0, 0) m，碰撞轮廓的东侧约 −0.463 m，在物理桌边西侧。CUDA 初始 host link 影子姿态未作为绘图输入。可用 [边界图脚本](../../../../../tools/variation/plot_nut_bolt_positions.py) 的 `--pick`、`--seat`、`--turn` 读取三份 CUDA 原始数据，`--robot-geometry-cpu` 读取 `raw/CPU.json`，最后用 `--output` 指定图目录。

- [54 行逐点表](POINTS.csv)
- CUDA 原始读数 · [PickBolt](raw/CUDA_PICK_BOLT.json) · [SeatNut](raw/CUDA_SEAT_NUT.json) · [TurnNut](raw/CUDA_TURN_NUT.json)
- [CPU 原始读数](raw/CPU.json)
- [直立根高与锁定位姿对照](raw/LOCK_Z_CONTROL.json)
- [TurnNut 零步 CUDA 角度诊断](raw/TURN_YAW_DIAGNOSTIC.json) · [诊断脚本](raw/TURN_YAW_DIAGNOSTIC.py.txt)
- [整桌图机器人根位姿与碰撞投影对照](raw/ROBOT_BASE_PROJECTION.json)
- [位置与动作检查器](../../../../../tools/variation/check_nut_bolt_positions.py)
- [范围与图](../README.md)
