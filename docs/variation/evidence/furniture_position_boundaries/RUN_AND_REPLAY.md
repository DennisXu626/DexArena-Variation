# 实测初态复现

使用与[运行报告](README.md#工程验证)相同的源码和 Windows 私有 SDK。项目 SDK 加载和二进制校验见[运行入口](../../../../tools/variation/sapien_sdk/README.md)。依赖装好后从仓库根目录执行。以下示例先按 seed 7 构造两个环境的基准回合，再在每个任务中复现标称和困难点。缩短测试可以在同一任务中只保留关注的样点。

```python
import gymnasium as gym
import torch
import tasks

make = dict(num_envs=2, sim_backend="physx_cuda", obs_mode="state",
            render_mode=None, control_mode="pd_joint_pos", reconfiguration_freq=0)

cases = {
    "LayFlatPanel": [
        ("N", 701, 0, {}),
        ("C-edge", 714, 1, {"rack_xy_m": [-.175, .19], "rack_yaw_deg": -10}),
    ],
    "InsertRail": [
        ("N", 701, 0, {}),
        ("LXY-2", 703, 0, {"rail_xy_m": [-.19, -.27]}),
        ("C-lane", 726, 1, {"rail_xy_m": [-.19, -.23], "rail_yaw_deg": 10,
                            "panel_xy_m": [-.145, -.072], "panel_yaw_deg": -7}),
    ],
    "FastenScrew": [
        ("N", 701, 0, {}),
        ("C-far", 715, 0, {"panel_xy_m": [-.115, -.048], "panel_yaw_deg": -7}),
    ],
}

for task, points in cases.items():
    with gym.make(f"FurnitureAssembly{task}-Sharpa-v1", **make) as env:
        env.reset(seed=7)
        for point, seed, i, request in points:
            obs, info = env.reset(seed=seed, options={
                "env_idx": torch.tensor([i], device=env.unwrapped.device),
                "position_layout": {str(i): request},
            })
            print(task, point, seed, i)
```

## 遥操作记录

| 任务 | 建议动作 |
|---|---|
| LayFlatPanel | `N` 从槽壁上方夹立板，抬过槽壁，翻至沟槽朝上并放入标记区。`C-edge` 的架底最接近桌边，同时与放置区间隙最小，比较槽两侧接近，记录哪一侧容易夹住后抬起。 |
| InsertRail | `N` 拾起导轨、对准喇叭口、沿 +X 送到止挡。`LXY-2` 分别观察能否抓起和能否对准低位槽口。`C-lane` 是导轨和斜置板件最紧组合，试上抬后从桌边侧对槽。 |
| FastenScrew | `N` 从翼部上方接近，沿顺时针方向转过原生成功门槛。`C-far` 自动短转探针未触及翼部，比较沿翼端接近和从斜上方接近后能否重新抓持。 |

每点回传任务 ID、样点 ID、动作是否完成、卡在接近/夹取/退出/对准/转动哪一步，以及较顺手的接近侧。操作者可从 [POINTS.csv](runtime_cuda/POINTS.csv) 继续挑选边界行。`expected_reject` 是接口拒绝测试。

## 批量重放与制图

`$sdk`、`$receipt`、`$physx` 指向经过同一 SDK 锁核验的私有 SAPIEN 目录、构件回执和 PhysX 目录。

```powershell
python -B -m tools.variation.check_furniture_positions --output outputs/position/furniture_cpu
python -B tools/variation/sapien_sdk/run_task_check.py --repo-root . `
  --checker tools/variation/check_furniture_positions.py --sapien-root $sdk `
  --artifact $receipt --physx-gpu-dir $physx --backend physx_cuda `
  --output outputs/position/furniture_cuda
python -B -m tools.variation.plot_furniture_positions `
  --runtime outputs/position/furniture_cuda/results.json --output outputs/position/figures
```

检查器需要新的输出目录。制图另从 Windows PhysX CPU 读取桌面碰撞盒和底座碰撞凸包，需要 Matplotlib 及一个中文字体。所有尺寸以任务源码、运行时几何和请求解析器为准。

当前代码默认运行含几何中心及边中点的完整矩阵。复用两个已归档 CUDA 批次制图时，`--runtime` 指定主批次 CSV 对应的 `results.json`，`--supplement` 指定补验 `results.json`。只复跑六个补验点时，向上面的 CUDA 检查命令追加 `--midpoint-only`。
