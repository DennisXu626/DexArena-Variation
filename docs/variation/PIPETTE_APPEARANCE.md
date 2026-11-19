# Pipette Transfer 外观

AspirateLiquid 与 DispenseLiquid 支持 original、jade、coral，保留六个可见逻辑对象的原版与两套额外外观。方案参数仅定义在[对象 catalog](../../assets/appearance/objects/pipette_transfer/catalog.json)；[运行索引](../../tasks/assets/variation/pipette_transfer/v1/catalog.json)引用参数、任务集合与绑定。

| 对象 | 正式绑定与保护 |
|---|---|
| 移液器 | 三 link 原生 articulation；仅 base.visual[0] 主体可变，其余五视觉完整 PBR、蓝柱塞及关节保留 |
| 样品杯 | 按壁、底、沿绑定；候选只改 RGB／受控 alpha，其余光学参数保留 |
| 试管 | 按壁、球底、沿绑定；动态刚体、质量和碰撞保留 |
| 试管架 | 原有支架视觉换材质，开口、几何和碰撞保留 |
| 支架／吸头杯 | 同一 Actor；tip_cup 是 stand.visual[4]，使用独立参数，未增加 Actor |

liquid_state 无视觉。所有方案保持机器人、位置规则、几何、碰撞、质量、关节、物理参数与成功判定。原资产、许可与文件身份见[资产审计](../../assets/appearance/objects/pipette_transfer/pipette/asset_audit.json)；原模型留在受忽略的授权资产目录，无新增 UV／贴图。

**配置与生命周期**

```python
import gymnasium as gym
import tasks

env = gym.make(
    "PipetteTransferAspirateLiquid-Sharpa-v1",
    pipette_appearance={"enabled": True, "scheme_id": "jade", "seed": 71},
    pipette_rendering={"enabled": True},
)
obs, info = env.reset(seed=7)
obs, info = env.reset(options={"pipette_appearance": {"scheme_id": "original"}})
records = env.unwrapped._pipette_appearance.records
```

省略外观配置或关闭时，不创建外观材质、随机流或记录器。启用时在建场前按环境克隆材质，保留组件内部原有共享拓扑，捕获完整原生 PBR；原任务及短任务阶段初始化完成后统一应用方案。original 准确恢复捕获值，render 不重抽方案。

覆盖顺序为构造公共 → 构造 `per_env` → reset 公共 → reset `per_env`。`per_env` 使用实际环境编号的标准字符串键（如 `"0"`）和字典值。外观启用时，公开 `reset` 在进入父类前校验所有选中环境的有效显式 ID 或完整 `random_choice` 列表。无效方案在任务初始化、抽样、物理写入和材质修改前即被拒绝。外观关闭时，合法形状的 reset 覆盖不会启用外观。

外观 RNG 按环境独立，显式方案不抽样。记录包含 `env_idx`、`episode_index`、`scheme_id`、`catalog_version`。`enabled` 和外观 `seed` 在构造时设置。局部 reset 隔离任务随机流、控制器缓冲及评价锁存状态。

显式 `env_idx` 必须严格递增，支持整数序列或一维整数张量。reset 使用当前设备的 long 索引，保持调用方参数不变。任务 seed 仅可随全环境 reset 设置。`reset_to_env_states` 走原生恢复路径并保留当前外观，组合 `pipette_appearance` 覆盖会遭拒绝。

[关闭示例](../../examples/variation/pipette_transfer/default.json) · [固定示例](../../examples/variation/pipette_transfer/fixed.json) · [随机示例](../../examples/variation/pipette_transfer/random.json)

**显式渲染配置**

`pipette_rendering` 默认关闭，保留原生 minimal 默认相机路径。候选要求显式启用经核定的修复 default 管线：按每环境真实 tip_cup render-id 修复目标片元深度，并在建场、GPU 批处理前将 sample_cup 固定到透明 gbuffer pass。杯体 PBR 及底盘原 alpha 保留，其余对象不改 pass；reset 不改 shading_mode、Scene version、相机或 images。

native_off、original、jade、coral 的验收统一使用上述“修复 default shaders＋sample cup 固定透明 pass”配置。original 指该配置下的原生 PBR 及精确像素恢复；不声称与 stock default 或 minimal 的 RGB 相同。私有 shader 包按来源／补丁身份缓存，逐环境绑定实际 ID，不修改安装目录、顶点或世界位置。材质与深度参数读取唯一 catalog。

**验收**

公开入口 CPU 合同使用记录副作用的父类替身，覆盖显式与随机有效请求、优先顺序、局部选择、恢复和 disabled 分支。未知方案用例的父 reset、任务和外观随机抽样、状态及锁写入计数均为零。

成功路径的 CPU、Windows v5 CUDA 和相机结果采用归档中记录的采集身份。见[正式运行摘要](../../assets/appearance/objects/pipette_transfer/previews/runtime/summary.json)和[任务相机补充检查](../../assets/appearance/objects/pipette_transfer/previews/runtime/rendering_probe_summary.json)。

| 检查 | 已验证范围 |
|---|---|
| 静态／CPU 合同 | 参数与保护角色、绑定、完整 original、原材质共享拓扑、配置覆盖、独立 RNG、非法请求原子性、局部 seed 拒绝；几何／判定／奖励／状态 AST 保持原定义 |
| 正式短任务接口 | 两任务关闭、original、两候选、随机复现、per_env／reset 覆盖及完整回合记录 |
| CPU 动态 | 每任务五设置各 60 步，共 600 control／12000 physics；native_repeat、original、两候选相对 native_off 的 61 个快照逐值精确一致，材质稳定 |
| 标准 CUDA 双环境 | 两任务共 46 次选中读回、4 control／80 physics；双向局部 reset 未选状态／控制器／随机流／记录精确不变，base、wrist、human 原相机 RGB 差 0，original 完整恢复 RGB 差 0 |
| 相机／深度补充 | 两布局 seed、七次毫米眼点变化、两种建批前深度设置，共 56 次构造、112 个 camera/env/view 对照；无显式控制步；目标外 RGB／depth 差 0，共同可见 tip 的 XYZ／Raw 不变，按记录 NDC 偏置变化 |

CUDA 使用显式 `two_env` GPU 缓冲容量配置；solver、contact、重力、休眠、频率、原相机尺寸与近远面保持任务定义。任何缓冲溢出、分配失败或 CPU 回退均失败。运行记录包含完整实际 SimConfig、源码／资产／外部 ManiSkill 文件闭包及私有 SDK 前后身份。

Aspirate 的部分原相机视图存在遮挡或无偏置时盘不可见，补充摘要逐项标记 visibility_limit；不对无共同像素处声称 XYZ 验证。结果限定记录的任务、seed、视距、相机和显式渲染配置。Long、Linux 运行、真实流体及完整机器人任务成功未验收。

**正式任务实景**

| 任务 | `pipette_appearance` 固定方案 | `pipette_rendering` |
|---|---|---|
| AspirateLiquid | [original](../../assets/appearance/objects/pipette_transfer/previews/runtime/AspirateLiquid/original_human_env0.png) · [jade](../../assets/appearance/objects/pipette_transfer/previews/runtime/AspirateLiquid/jade_human_env0.png) · [coral](../../assets/appearance/objects/pipette_transfer/previews/runtime/AspirateLiquid/coral_human_env0.png) | 显式启用。样品杯透明 pass 和承托盘深度偏置 |
| DispenseLiquid | [original](../../assets/appearance/objects/pipette_transfer/previews/runtime/DispenseLiquid/original_human_env0.png) · [jade](../../assets/appearance/objects/pipette_transfer/previews/runtime/DispenseLiquid/jade_human_env0.png) · [coral](../../assets/appearance/objects/pipette_transfer/previews/runtime/DispenseLiquid/coral_human_env0.png) | 显式启用。承托盘深度偏置 |

**复现**

```powershell
python -B tools/variation/check_pipette_runtime.py --static --baseline origin/main
python -B tests/test_pipette_appearance.py
python -B tools/variation/check_static.py
python -B tools/variation/check_appearance_archive.py
```

按[SDK 说明](../../tools/variation/sapien_sdk/README.md)准备 runtime、artifact 与 PhysX 路径，使用[通用启动器](../../tools/variation/sapien_sdk/run_task_check.py)运行 `check_pipette_runtime.py --approved-runtime --sim-backend physx_cuda --experimental-windows-cuda --gpu-memory-profile two_env --task AspirateLiquid`，DispenseLiquid 另进程运行；输出目录必须全新。启动器在原生导入前保留系统 Vulkan loader，并前后核对加载路径和 SHA256。

CPU 使用 `check_pipette_dynamics.py --steps 60 --seed 7`，父进程传入 `--sapien-root --artifact --physx-gpu-dir`，每个 worker 独立核验 SDK。`check_pipette_rendering.py` 采集相机补充证据；`compact_pipette_rendering.py` 直接复核其 PNG／NPZ／PT。

[正式证据导出器](../../tools/variation/compact_task_runtime.py) 使用 `--family pipette_transfer`、每项 CUDA 的 `--run / --console-run`、CPU 的 `--cpu-run / --cpu-console-run`、`--sdk-artifacts / --sdk-lock`、光学 `--probe-summary` 和新的 `--output` 目录。导出过程直接检查原始状态和图像，保留原 PNG 字节。
