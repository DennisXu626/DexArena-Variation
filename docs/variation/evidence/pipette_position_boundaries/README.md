# Pipette Transfer 位置边界与遥操作

`AspirateLiquid` 用右手从支架取竖直移液器，在样品皿内完成吸液，再归还支架。`DispenseLiquid` 用左手从同一支架取移液器，在架中的中央试管内排液，再归还支架。两段通过同一停放位交接。排液时试管留在架内。`Long` 继承同一初始布置，并由原生评估器从吸液阶段推进到排液阶段。

| 任务与变量 | 世界坐标标称与旧域 | 候选域 | 跟随物与边界 |
|---|---|---|---|
| 两短任务及 Long · [支架 XY](01_stand_xy.png) | (−15, −17) cm。原生两轴连续 ±2 cm | X 连续 ±3 cm，Y 连续 −3 至 +1 cm | 支架底板、后立柱、导向圈与停放的移液器一起平移。改变取管与归还距离。 |
| 两短任务及 Long · [支架朝向](02_stand_yaw.png) | 世界 +Z 转角 90°。原生连续 ±10° | 78°、90°、102° | 同一后立柱绕支架中心转，移液器沿竖直轴停放，保留原生四元数。 |
| AspirateLiquid、Long · [样品皿 XY](03_sample_dish_xy.png) | (−17, −2) cm。原生两轴连续 ±2 cm | X 连续 ±3.5 cm，Y 连续 −1 至 +4 cm | 改变从支架取管后将吸头移入皿的方向及距离。皿的支撑、内区和姿态随本次实际圆心。 |
| DispenseLiquid、Long · [试管架 XY](04_tube_rack_xy.png) | (−17, 24) cm。原生两轴连续 ±2 cm | X 连续 ±4 cm，Y 连续 ±3 cm | 试管随架中央槽平移。排液以实时管口为准，检验双层槽壁的余量及上方接近空间。 |

候选值以 [`position_layout.py`](../../../../tasks/pipette_transfer/position_layout.py) 为准。列中的 XY 是场景轴，表记录相对标称的偏移，API 接收绝对米值。含皿的场景同时要求旋转后支架底板与皿碰撞带留有至少 2 cm 的净距下界。单变量图固定其余量为标称值，多个范围组合时仍须通过净距检验。旧域为原生抽样提案，原生采样仍按原来的间距规则重抽。

## 复现

使用 [运行报告](RESULTS.md) 所列 SDK 和后端。相同场景编号下，先以该行 `seed` 全量 reset，再按 `reset_options` 只重置选中的环境。局部 reset 由原任务要求省略 `seed`。显式空行 `{}` 是该环境的标称工作站。省略整个 `position_layout` 时使用原生抽样，机器人的初始化随机流保持一致。保存在逐点表中的负例用于复现拒绝。

```python
import csv
import json
import gymnasium as gym
import tasks

with open("docs/variation/evidence/pipette_position_boundaries/POINTS.csv",
          encoding="utf-8", newline="") as stream:
    row = next(item for item in csv.DictReader(stream)
               if item["task"] == "PipetteTransferAspirateLiquid-Sharpa-v1"
               and item["id"] == "C-gap")
env = gym.make(row["task"], **json.loads(row["make_kwargs"]))
env.reset(seed=int(row["seed"]))
obs, info = env.reset(options=json.loads(row["reset_options"]))
selected = int(row["env_idx"])
```

遥操作先从两短任务各自的 `stand-xy / N0` 取管。接着在吸液 `C-gap` 试抬高吸头越过上导向圈，再从支架移向近皿。排液试 `C-far`，从远支架取管，把吸头移到远侧管口上方，再归还原支架。回传任务与样点 ID、完成的步骤、受阻位置及顺手的接近方向。坐标、姿态、阶段和指尖目标可从 [逐点表](POINTS.csv) 读回。
