# Office Desk 逐点复现

运行前按仓库说明准备授权的 10211、13106、101408 与原生机器人资源。三个正式环境均通过现有 Gymnasium 入口构建。`position_layout` 的键为本次选中环境的字符串编号，值为该任务设备的字段组。每次显式请求先校验所有行，再初始化。空字段组取设备标称位姿。省略整个请求时走原生采样。

| 任务 | XY 字段（m） | 相对型号朝向（°） |
|---|---|---|
| `OfficeDeskOpenLaptop-Sharpa-v1` | `laptop_xy_m` | `laptop_yaw_offset_deg` |
| `OfficeDeskTypeKeys-Sharpa-v1` | `keyboard_xy_m` | `keyboard_yaw_offset_deg` |
| `OfficeDeskClickMouse-Sharpa-v1` | `mouse_xy_m` | `mouse_yaw_offset_deg` |

从报告的逐点表选择 `initialization` 行，使用行内构造参数、seed、完整请求和 `env_idx` 读回对应的虚拟场景。以下示例从仓库根目录运行。

```python
import csv
import json
from pathlib import Path

import gymnasium as gym
import tasks

evidence = Path("docs/variation/evidence/office_position_boundaries")
with (evidence / "cpu/TypeKeys/POINTS.csv").open(encoding="utf-8", newline="") as stream:
    row = next(point for point in csv.DictReader(stream) if point["id"] == "N")
env = gym.make(row["task"], **json.loads(row["make_kwargs"]))
observation, info = env.reset(seed=int(row["seed"]), options=json.loads(row["reset_options"]))
selected = int(row["env_idx"])
print(info["keyboard_root_pose"][selected])
```

采用双环境 CUDA 的 `indexed_isolation` 行时，先用同一 seed 全量 reset 两边的标称显式位置，再按行内 `reset_options` 单边 reset。局部调用省略 seed。隔离原始记录还包括非零阶段计数的检查器夹具及两次快照间的字段对照。

每个任务目录的 `results.json` 包含逐点读回、IK 目标和误差、短时仿真轨迹、原生资源和代码身份。`POINTS.csv` 中 `expected_rejection` 用于验证非法输入。图形可从同一次后端采集再生。

```powershell
python tools/variation/check_office_positions.py --task TypeKeys --backend physx_cpu --output outputs/office_positions/cpu/TypeKeys
python tools/variation/plot_office_positions.py outputs/office_positions/cpu docs/variation/evidence/office_position_boundaries
```

Windows CUDA 使用项目的 [私有 SDK 启动器](../../../../tools/variation/sapien_sdk/README.md)，将检查器设为 `tools/variation/check_office_positions.py` 并使用 `--backend physx_cuda`。运行证据记录所用 DLL、SAPIEN 版本及 indexed reset 能力。ClickMouse 使用原生 CoACD 1.0.14 与授权模型自带的缓存输入。
