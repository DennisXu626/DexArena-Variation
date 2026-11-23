# 位置初始化与遥操作复现

三短任务支持在 `env.reset(options=...)` 中传 `position_layout`。本次 reset 的每个选中环境都有一个字符串键。省略整个 `position_layout` 时执行原生采样。显式请求中的位移是总位移，单位 m，朝向单位度。配置校验完成后再写入选中环境的姿态。

| 任务 | 位置字段 | 省略字段时的含义 |
|---|---|---|
| OpenDrawer | `drawer_xy_m`、`drawer_yaw_deg` | 柜根 (0.18,0.18) m，0°，中屉关闭 |
| PickCharger | 上述两个字段、`charger_drawer_local_xy_m` | 柜根标称，开度 0.22 m，charger 中心取原生屉内标称点 |
| InsertPlug | `socket_xy_m`、`socket_yaw_deg`、`charger_table_xy_m` | 插座标称 (−0.125,−0.38) m、90°，Charger 从原生 0.105 m 圆盘采样 |

屉内 Charger 的坐标按零开度的柜根定义。应用时先在局部 x 减掉开度，再根据柜体朝向旋转并平移。Charger 侧躺及插脚朝内的姿态一并随柜体旋转。把手位置由同一柜体运动和滑轨行程决定；取物判定以当前抽屉坐标计算。插入判定继续用插座实时位姿逆变换，孔距、孔深和阈值沿用原生任务。旧回放中的 18 列任务状态和物理姿态依然通过原入口恢复。

[逐点复现表](POINTS.csv)中类别 `initialization` 可用于重建位置。取同一行的 task、seed、env_idx、make_kwargs 和 reset_options。下面以西端的 InsertPlug 为例。

```python
import csv
import json
import gymnasium as gym
import torch
import tasks

with open("POINTS.csv", encoding="utf-8", newline="") as stream:
    row = next(p for p in csv.DictReader(stream)
               if p["task"] == "DrawerPlugInsertPlug-Sharpa-v1" and p["id"] == "F4-5")
env = gym.make(row["task"], **json.loads(row["make_kwargs"]))
env.reset(seed=7)
options = json.loads(row["reset_options"])
options["env_idx"] = torch.as_tensor(options["env_idx"], device=env.unwrapped.device)
obs, info = env.reset(seed=int(row["seed"]), options=options)
```

其中 Charger 明确位于 (−0.395,−0.61) m。想复现其它试验行时，用该行的 env 编号、seed 和请求。若构建在相同后端和依赖下，还要核对表中实际位置、四元数和任务阶段。原生随机轨迹受此前的随机流消耗影响，单跑一行时应按实测值复核。

`placement_predicate` 是在真实 PickCharger 环境中另行构造的桌面侧躺状态，属于放置判据测试。此类行不属于可初始化请求。**图中侧躺姿态推荐世界 X ≥ −0.3965 m**。若换向或倾斜，须将真实壳体投影变换到世界坐标再检查桌边；14 cm 原生成功门槛依旧按中心距离及其它原生条件判断。
