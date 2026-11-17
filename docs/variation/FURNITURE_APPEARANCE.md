# Furniture Assembly 四对象外观

三个 Sharpa 短任务的外观接口与限定运行验证已完成。Long 未接入；物体总状态待团队审阅。

## 接口与方案

[运行 catalog](../../tasks/assets/variation/furniture_assembly/v1/catalog.json)版本为 `furniture-appearance-v1`，统一方案为 `original`、`variant_1`、`variant_2`；各对象 catalog 是唯一数值源。

| 正式任务 ID | 外观对象 |
|---|---|
| FurnitureAssemblyLayFlatPanel-Sharpa-v1 | 板件、导向架 |
| FurnitureAssemblyInsertRail-Sharpa-v1 | 板件、导轨、十字槽螺钉 |
| FurnitureAssemblyFastenScrew-Sharpa-v1 | 板件、导轨、翼形螺钉 |

[适配器](../../tasks/furniture_assembly/appearance.py)仅覆盖可变部件的 `base_color`、`roughness`、`metallic`，几何、碰撞和物理参数保持原定义。省略配置或 `enabled=false` 保留原生材质与 jitter；`original` 恢复本次建场捕获的原生材质。候选在回合初始化后应用并保持固定。

配置优先级：构造公共配置 → 构造 `per_env` → reset 公共配置 → reset `per_env`，环境键使用字符串。`explicit` 指定 `scheme_id`；`random_choice` 从非空 `scheme_ids` 中选择。`enabled` 和外观随机源 `seed` 仅构造时生效。

[default](../../examples/variation/furniture_assembly/default.json)、[fixed](../../examples/variation/furniture_assembly/fixed.json)、[random](../../examples/variation/furniture_assembly/random.json)示例包含 `task_id` 与构造参数；加载 JSON 后先取出 `task_id`。

## 构造与 reset

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
    furniture_appearance={"enabled": True, "mode": "explicit", "scheme_id": "variant_1",
                          "per_env": {"1": {"scheme_id": "variant_2"}}},
)
obs, info = env.reset(seed=7)
obs, info = env.reset(options={
    "env_idx": torch.tensor([1], device=env.unwrapped.device),
    "furniture_appearance": {"mode": "explicit", "scheme_id": "original"},
})
records = env.unwrapped._furniture_appearance.records
env.close()
```

记录字段为 `env_idx`、`episode_index`、`scheme_id`、`catalog_version`；回合索引按环境递增，包含构造时的初始化。局部 reset 的随机流、每环境控制器缓冲和任务状态隔离修复独立于外观开关；[Franka reset](../../tasks/robots/franka_joint_impedance_controller.py)按选中 mask 更新已有目标。

外观协议与 Mouse 保持一致；选中环境的外观请求在外观抽样和材质更新前统一校验。[Mouse 兼容性复核](evidence/furniture_assembly/mouse_compatibility_20261117.json)在同一 SDK 上通过原验收及 main 对照，未引入运行回归；Mouse 已有的强动态隔离缺口不在本 PR 扩改。共享控制器修复会更新采集代码指纹，新增数据使用新版本目录，不与旧 Mouse 采集版本混录。

## 部件与来源

| 对象与数值源 | variant_1 / variant_2 | 可变与保留部件 |
|---|---|---|
| [板件](../../assets/appearance/objects/furniture_assembly/flat_panel/README.md) · [catalog](../../assets/appearance/objects/furniture_assembly/flat_panel/variants/v1/catalog.json) | 浅象牙 / 深蓝 | 改主面、槽底、封边、槽沿；保留标签与条码 |
| [导向架](../../assets/appearance/objects/furniture_assembly/panel_rack/README.md) · [catalog](../../assets/appearance/objects/furniture_assembly/panel_rack/variants/v1/catalog.json) | 深蓝 / 浅灰白 | 改主体与底板；保留垫片、螺栓、黄条 |
| [导轨](../../assets/appearance/objects/furniture_assembly/rail/README.md) · [catalog](../../assets/appearance/objects/furniture_assembly/rail/variants/v1/catalog.json) | 深蓝 / 香槟铜 | 改主体与槽唇，仅绑定 rail_body |
| [螺钉](../../assets/appearance/objects/furniture_assembly/screw/README.md) · [catalog](../../assets/appearance/objects/furniture_assembly/screw/variants/v1/catalog.json) | 深青 / 砖红 | 改头部握持面；保留十字槽几何、金色顶帽或黄铜杆与方向顶条 |

各对象 `bindings.json` 保存角色、任务表示与证据入口。方案使用仓库程序材质，无新增贴图、模型或字体；代码与原资产许可分别见 [LICENSE](../../LICENSE)和[资产说明](../../tasks/assets/README.md)。

## 验证与复现

[正式运行证据](../../assets/appearance/furniture_assembly/previews/runtime_check_20261117/summary.json)记录版本、源码哈希与三任务结果。

| 检查 | 实测结果 |
|---|---|
| CPU 动态对照 | 三任务 × 四种设置，720 control steps / 14400 physics steps；初态、逐步物理状态、关节目标、任务记录及 success/reward 数值差 0 |
| GPU 双环境 | 三任务各 2 环境，6 control steps / 120 physics steps；原 ManiSkill 标准 CUDA RGB，66 次选中环境检查通过 |
| 未重置 env0 | 物理状态、每环境控制器缓冲、任务与外观随机流、RGB 均精确保持，最大差 0 |
| original 恢复 | 两环境原相机 RGB 最大差 0 |
| 选中环境读回 | actor/articulation 物理状态最大绝对误差约 `2.3841858e-7`；`rtol=0`、`atol=2e-6` |

CPU 动态对照使用新输出目录复现：

```bash
python -B tools/variation/check_furniture_dynamics.py --output outputs/furniture_cpu_check --steps 60 --seed 7
```

固定视角初态外观图保留于 [435f835 的 003 历史预览](https://github.com/DennisXu626/DexArena-Variation/tree/435f835038d22cfe21b452681747cf3d85d6a67c/assets/appearance/furniture_assembly/previews/author_check_20261116)。
