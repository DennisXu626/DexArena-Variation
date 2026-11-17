# Meal Preparation 外观 Variation

本实现随 [PR #8](https://github.com/DennisXu626/DexArena-Variation/pull/8) 提交，限定技术验收通过，待整合/合并；依据[查收审阅](https://github.com/DennisXu626/DexArena-Variation/pull/8#pullrequestreview-5919739591)，集成状态见[PR8](https://github.com/DennisXu626/DexArena-Variation/pull/8)。[当前能力与限制](STATUS.md)及[归档证据](evidence/meal_preparation/README.md)记录实际检查范围、恢复原版和历史收据。
本目录的实现使用备餐任务原有的程序生成午餐盒和 RoboCasa 视觉资产。通过 `meal_appearance` 在建场时为每个环境绑定独立的可变渲染材质，在回合 reset 时应用指定方案。几何、碰撞、质量、关节和成功判定沿用原任务。

## 方案和部件

| 对象 | 实际绑定 | 方案一 | 方案二 |
| --- | --- | --- | --- |
| 午餐盒 | `box_base` 外壳／后叶、独立内底、`box_lid` 盒盖。圆柱铰链保留原材质 | 雾蓝灰哑光 | 砖红盒身、浅陶土红盒盖 |
| 盘子 `plate_0` | `plate_top` 与 `plate_bottom` | 钴蓝亮釉、浅灰蓝盘底 | 暖白、原 UV 生成墨绿盘沿 |
| 勺子 `spoon_16` | 勺体 `wire_140088225`，程序生成握套单独绑定 | 亮银、深蓝握套 | 石墨灰、暖橙握套 |
| 贝果 `bagel_5` | `Material.052`，按原 UV 调整已安装的 `visual/image0.png` | 浅烘金黄 | 深烘栗棕 |
| 番茄 `tomato_2` | 红色主体 `default.012`，其它三个材质槽保留 | 金黄 | 紫红 |

[方案参数](../../tasks/assets/variation/meal_preparation/v1/catalog.json)是运行时唯一参数源。没有新增 UV。盘沿和贝果贴图由[贴图生成代码](../../tasks/meal_preparation/appearance_textures.py)在首次需要时生成，并在同一实例的子环境间复用只读 CPU 像素。需要切换贴图的材质持有独立 GPU 纹理，以便在 SAPIEN 3.0 批量相机中原地更新且不串色。贝果的衍生贴图依赖使用者已有授权的 RoboCasa 资产，由运行时生成。仓库交付包含配方和参数。

开盒短任务只加载午餐盒和基础版勺子。放面包、舀番茄和长任务加载全部对象。短柄勺、小尺寸番茄和程序盒盖仍按各阶段原配置构建。启用外观时以以上已核对的资产标识为准。

## 使用

省略 `meal_appearance` 或设置 `enabled: false` 即走原生材质路径。开启后 `original` 是默认方案。设置 `mode: random_choice` 和 `scheme_ids` 可从集合选择，`seed` 控制独立的外观随机源。

```python
import gymnasium as gym
import torch
import tasks

env = gym.make(
    "MealPreparationLong-Sharpa-v1",
    num_envs=2, sim_backend="physx_cuda", obs_mode="rgb",
    render_mode="rgb_array", reconfiguration_freq=0,
    meal_appearance={"per_env": {
        "0": {"scheme_id": "variant_1"}, "1": {"scheme_id": "variant_2"},
    }},
)
env.reset(seed=7)
env.reset(options={
    "env_idx": torch.tensor([1], device=env.unwrapped.device),
    "meal_appearance": {"per_env": {"1": {"scheme_id": "original"}}},
})
print(env.unwrapped.meal_appearance.records)
env.close()
```

`records` 保存每个环境最近一次任务初始化时的方案 ID、目录版本和回合序号。材质在回合间由 reset 选择。验证覆盖正常 reset 流程。

## 并行验收

使用集群已授权的 GPU 作业，配置 `ROBOCASA_ASSET_DIR` 指向备餐所用 RoboCasa 对象目录。

```bash
python -B tools/variation/check_meal_parallel.py --mode isolation --output outputs/meal_parallel
python -B tools/variation/check_meal_parallel.py --mode baseline --output outputs/meal_parallel
python -B tools/variation/check_meal_parallel.py --mode enabled --output outputs/meal_parallel
```

隔离检验在四个任务分别创建 2 个环境，对比 Variation 关闭和开启。开启时先让两环境使用不同方案，只重置 env1 并切到原版，比较 env0 的状态、随机流、材质、方案记录和各 RGB 相机。检查期间无物理步进。任何状态数值差须不超过 `1e-6`，每路 RGB 容许最多 8 个通道值产生 1 级量化差，报告保存实际差值。

计时在长任务上使用同一 GPU 和 2 个环境，开关模式各用一个进程。首次 `gym.make` 包括加载、实例化和构造 reset。预热后测 20 次局部 reset（含 RGB）、30 次步进（含 RGB）及 20 次 human 渲染。GPU 进程显存按阶段采样，Torch 分配器峰值单独记录。


并行路径修复了勺子在 CUDA 场景缓冲区就绪前写入位姿的问题。任务 reset 会在缓冲区就绪后应用原校准位姿。回合位姿、盒盖目标和原生随机流按真实环境索引更新，防止局部 reset 覆盖整批数据。成功判定函数保持原实现。

## 实测结果

Slurm 作业 `86563` 在 lyg0295 的 G0 上完成。运行使用 PhysX CUDA、SAPIEN 3.0.3、ManiSkill 3.0.0b22 和 Torch 2.12.0.dev20260408+cu128。

四个任务各 2 个环境。env0 的实际材质参数和贴图哈希、回合记录与原生及外观随机流保持一致。未选状态最大绝对数值差为 2.39e-7。长任务四路 RGB 逐值一致。三个短任务每路最多一个通道值变化 1/255，关闭 Variation 的对照也出现同量级差异。选中环境成功恢复原版纹样。长任务前帧核对到暖橙握套和钴蓝盘，局部 reset 后原绿边上的 405 个采样像素均发生真实变化。

| 长任务 2 env | 关闭 | 开启 | 样本数每组 |
| --- | ---: | ---: | ---: |
| 首次构造及加载 | 4.577 s | 6.316 s | 1 |
| 局部 reset，含 RGB | 44.43 ms | 53.79 ms | 20 |
| 单步，含 RGB | 653.86 ms | 655.92 ms | 30 |
| Human RGB | 1.716 ms | 1.716 ms | 20 |
| 进程 GPU 显存，阶段采样最大值 | 2047 MiB | 2047 MiB | 4 |

重复操作给出中位数。显存为采样值，未测到增量不证明独立纹理无显存成本。测量限定在本作业的双环境。大批量吞吐及完整机器人长任务回放仍待验证。


历史任务判定、双环境隔离及恢复原版验收见 [运行证据索引](evidence/meal_preparation/README.md)。

PR8-R2仅做文档及短时静态核对，不执行上述GPU示例。[收尾索引](evidence/meal_preparation/PR8-R2.md)保留R1已关闭项并核对新增补档。随机选择复现只限CPU逻辑；真实GPU随机路径、更多环境／手型、PartNet午餐盒和完整机器人长任务成功未纳入。限定技术验收依据[PR8-R2查收审阅](https://github.com/DennisXu626/DexArena-Variation/pull/8#pullrequestreview-5919739591)，当前待整合/合并；集成状态见[PR8](https://github.com/DennisXu626/DexArena-Variation/pull/8)。
