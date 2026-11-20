# Furniture Assembly 外观

为板件、导向架、导轨和螺钉提供原版及十套外观，通过 `furniture_appearance` 在建场时绑定每环境私有材质，在 reset 时选择方案并记录。几何、碰撞、质量、关节和任务判定沿用原任务。

## 方案与部件

[运行 catalog](../../tasks/assets/variation/furniture_assembly/v1/catalog.json)版本为 `furniture-appearance-v1`，支持 `original` 和 `variant_1` 至 `variant_10`。各对象 catalog 是材质参数的唯一来源。

| 正式任务 ID | 外观对象 |
|---|---|
| FurnitureAssemblyLayFlatPanel-Sharpa-v1 | 板件、导向架 |
| FurnitureAssemblyInsertRail-Sharpa-v1 | 板件、导轨、十字槽螺钉 |
| FurnitureAssemblyFastenScrew-Sharpa-v1 | 板件、导轨、翼形螺钉 |

| 对象与数值源 | 原有两套候选 | 可变与保留部件 |
|---|---|---|
| [板件](../../assets/appearance/objects/furniture_assembly/flat_panel/README.md) · [catalog](../../assets/appearance/objects/furniture_assembly/flat_panel/variants/v1/catalog.json) | 浅象牙 / 深蓝 | 改主面、槽底、封边、槽沿；保留标签与条码 |
| [导向架](../../assets/appearance/objects/furniture_assembly/panel_rack/README.md) · [catalog](../../assets/appearance/objects/furniture_assembly/panel_rack/variants/v1/catalog.json) | 深蓝 / 浅灰白 | 改主体与底板；保留垫片、螺栓、黄条 |
| [导轨](../../assets/appearance/objects/furniture_assembly/rail/README.md) · [catalog](../../assets/appearance/objects/furniture_assembly/rail/variants/v1/catalog.json) | 深蓝 / 香槟铜 | 改主体与槽唇，仅绑定 rail_body |
| [螺钉](../../assets/appearance/objects/furniture_assembly/screw/README.md) · [catalog](../../assets/appearance/objects/furniture_assembly/screw/variants/v1/catalog.json) | 深青 / 砖红 | 改头部握持面；保留十字槽几何、金色顶帽或黄铜杆与方向顶条 |

新方案在批准的部件上调整 RGB、粗糙度和金属度。各对象沿用同一色系，并按零件用途选取饰面。板件保持非金属，标签、条码、方向标记和其他保留部件沿用原版材质。

| 方案 | 色系 | 饰面 |
|---|---|---|
| `variant_3` | 酒红 | 哑光木饰面、粉末涂层 |
| `variant_4` | 琥珀橙 | 缎面木饰面、阳极金属质感 |
| `variant_5` | 柠檬绿 | 低反射木饰面、哑光涂漆金属 |
| `variant_6` | 松绿 | 细哑光木饰面、缎面导轨 |
| `variant_7` | 湖青 | 亮面漆板、亮面金属 |
| `variant_8` | 鸢尾紫 | 缎面漆板、亮缎面金属 |
| `variant_9` | 玫瑰粉 | 亮漆木饰面、喷涂金属 |
| `variant_10` | 石墨灰 | 缎面木饰面、高金属度饰面 |

[适配器](../../tasks/furniture_assembly/appearance.py)仅覆盖可变部件的 `base_color`、`roughness`、`metallic`。各对象 `bindings.json` 保存角色及任务表示。方案使用程序材质，无新增贴图、模型或字体；代码与原资产许可分别见 [LICENSE](../../LICENSE)和[资产说明](../../tasks/assets/README.md)。

## 使用

省略配置或设置 `enabled=false` 保留原生材质与 jitter；`original` 恢复本次建场捕获的原生材质。候选在回合初始化后应用并保持固定。

配置优先级：构造公共配置 → 构造 `per_env` → reset 公共配置 → reset `per_env`，环境键使用字符串。`explicit` 指定 `scheme_id`；`random_choice` 从非空 `scheme_ids` 中选择。`enabled` 和外观随机源 `seed` 仅构造时生效。

[default](../../examples/variation/furniture_assembly/default.json)、[fixed](../../examples/variation/furniture_assembly/fixed.json)、[random](../../examples/variation/furniture_assembly/random.json)示例包含 `task_id` 与构造参数；加载 JSON 后先取出 `task_id`。

GPU 局部 reset 要求 SDK 原生函数 `sapien.physx.indexed_gpu_apply_patch_version()` 返回 `1`。Windows 验证包为 `3.0.3+dexarena.gpu1.wininterop5`；构建与加载方法见 [SDK 说明](../../tools/variation/sapien_sdk/README.md)。CPU 不受此能力检查影响。

先在同一进程执行 [SDK 说明](../../tools/variation/sapien_sdk/README.md)的普通脚本加载片段，再运行：

```python
import torch
torch.cuda.init()
import gymnasium as gym
import tasks

env = gym.make(
    "FurnitureAssemblyLayFlatPanel-Sharpa-v1",
    num_envs=2, sim_backend="physx_cuda", obs_mode="rgb", render_mode="rgb_array",
    reconfiguration_freq=0,
    furniture_appearance={"enabled": True, "mode": "explicit", "scheme_id": "variant_10",
                          "per_env": {"1": {"scheme_id": "variant_3"}}},
)
env.reset(seed=7)
env.reset(options={
    "env_idx": torch.tensor([1], device=env.unwrapped.device),
    "furniture_appearance": {"mode": "explicit", "scheme_id": "original"},
})
records = env.unwrapped._furniture_appearance.records
env.close()
```

`records` 追加 `env_idx`、`episode_index`、`scheme_id`、`catalog_version`；回合索引按环境递增，包含构造时的初始化。选中环境的外观请求在抽样和材质更新前统一校验。局部 reset 按环境索引更新任务随机流、物理状态及[控制器目标](../../tasks/robots/franka_joint_impedance_controller.py)，外观开关关闭时同样生效。

## 验证与复现

[本轮结果](../../assets/appearance/furniture_assembly/previews/runtime_finishes/summary.json)记录三项短任务的输入哈希、实测结果和图片索引。[首批验收](../../assets/appearance/furniture_assembly/previews/runtime/summary.json)保留原有两套外观的历史结果。

| 检查 | 本轮结果 |
|---|---|
| CPU 接口 | 三任务均验证默认关闭、全部 11 个固定方案、随机选择、配置覆盖、低细节模式和原版恢复。 |
| CPU 动态 | 每任务用相同种子和动作运行两次关闭外观的对照、原版及十候选，各 60 步。共 2,340 控制步、46,800 物理子步，逐步状态和奖励一致。 |
| 标准 CUDA | 每任务两个环境，共 114 次选中读回、6 控制步、120 物理子步。双向局部 reset 时，未选环境的物理状态、控制器、随机流和画面保持一致。 |
| 恢复原版 | 八套新外观逐套恢复原版，两个环境的原生相机均逐像素一致。 |

在同一初态用任务原生 `base_camera` 比较外观。每个目录含 11 张方案原图和四张局部 reset 对照图。

| 任务 | 图集 | 新外观示例 |
|---|---|---|
| LayFlatPanel | [板件与导向架](../../assets/appearance/furniture_assembly/previews/runtime_finishes/LayFlatPanel/) | [湖青](../../assets/appearance/furniture_assembly/previews/runtime_finishes/LayFlatPanel/variant_7_base_camera_env0.png) |
| InsertRail | [板件、导轨与十字槽螺钉](../../assets/appearance/furniture_assembly/previews/runtime_finishes/InsertRail/) | [鸢尾紫](../../assets/appearance/furniture_assembly/previews/runtime_finishes/InsertRail/variant_8_base_camera_env0.png) |
| FastenScrew | [板件、导轨与翼形螺钉](../../assets/appearance/furniture_assembly/previews/runtime_finishes/FastenScrew/) | [琥珀橙](../../assets/appearance/furniture_assembly/previews/runtime_finishes/FastenScrew/variant_4_base_camera_env0.png) |

[env0 保持石墨灰](../../assets/appearance/furniture_assembly/previews/runtime_finishes/LayFlatPanel/local_0_base_camera_env0.png)，[env1 从酒红恢复原版](../../assets/appearance/furniture_assembly/previews/runtime_finishes/LayFlatPanel/local_0_base_camera_env1.png)。每张对照图左侧为 reset 前，右侧为 reset 后。下一轮交换选中和未选中的环境。

从仓库根目录运行。每次选择新的输出目录。

```bash
python -B tools/variation/check_furniture_appearance.py --static
python -B tools/variation/check_furniture_appearance.py --approved-runtime --sim-backend physx_cpu --output outputs/furniture_interface
python -B tools/variation/check_furniture_dynamics.py --steps 60 --seed 7 --output outputs/furniture_dynamics
```

Windows CUDA 按 [SDK 验证入口](../../tools/variation/sapien_sdk/README.md)加载私有 v5 SDK。验证入口默认遍历三个短任务，也可用 `--task` 逐任务采集。预览工具支持 `--scheme variant_7`，窗口中 `N`、`B` 切换方案，`V` 切换固定视图。

本轮验收范围为 Windows 上的三个短任务和上述动作序列。
