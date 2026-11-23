# Office Desk 真实版外观

OpenLaptop、TypeKeys、ClickMouse 各有原版与十套日常饰面。笔记本和独立键盘也各有一套独立选择的键帽目录，均为原版与十套候选。原有公开 ID 保留，材质参数由对应 catalog 提供。

| 正常任务入口 | 外观配置 | 目录 |
|---|---|---|
| `OfficeDeskOpenLaptop-Sharpa-v1` | `office_devices_appearance` | [屏框](../../assets/appearance/objects/office_desk/laptop/catalog.json) |
| `OfficeDeskOpenLaptop-Sharpa-v1` | `office_keyboard_appearance` | [内置键帽](../../assets/appearance/objects/office_desk/laptop/keycaps_catalog.json) |
| `OfficeDeskTypeKeys-Sharpa-v1` | `office_devices_appearance` | [壳体与装饰边](../../assets/appearance/objects/office_desk/keyboard/catalog.json) |
| `OfficeDeskTypeKeys-Sharpa-v1` | `office_keyboard_appearance` | [独立键帽](../../assets/appearance/objects/office_desk/keyboard/keycaps_catalog.json) |
| `OfficeDeskClickMouse-Sharpa-v1` | `mouse_appearance` | [壳体、按钮与滚轮](../../tasks/assets/variation/office_desk/mouse_101408/v1/catalog.json) |

屏框选用哑光或缎面阳极铝、粉末涂层及陶瓷质感涂层。独立键盘外壳与装饰边分别配色，键帽使用低光泽 ABS 或 PBT 饰面。两套键帽目录均有分区配色，按字键区和外圈功能区单独设置配色，形成深浅与冷暖对比。独立键盘沿用原始印刷字标，鼠标以注塑壳体和按钮搭配橡胶感滚轮。材质分区可参考 [Dennis #20](https://github.com/DennisXu626/DexArena-Variation/pull/20) 和 [RoboDojo 材质库](https://huggingface.co/datasets/RoboDojo-Benchmark/RoboDojo/tree/main/Assets/Material)。

## 独立选择和复位

任一外观配置默认关闭。下面的任务只启用笔记本键帽，独立键盘使用同一配置键。壳体与键帽也可以同时启用，并分别选择方案。

```python
import gymnasium as gym
import tasks
import torch

env = gym.make(
    "OfficeDeskOpenLaptop-Sharpa-v1",
    num_envs=2,
    sim_backend="physx_cuda",
    obs_mode="rgb",
    render_mode="rgb_array",
    office_devices_appearance={"enabled": False},
    office_keyboard_appearance={
        "enabled": True,
        "scheme_id": "variant_3",
        "per_env": {"1": {"scheme_id": "variant_8"}},
    },
)
env.reset(seed=7)
env.reset(options={
    "env_idx": torch.tensor([1], device=env.unwrapped.device),
    "office_keyboard_appearance": {"scheme_id": "original"},
})
```

公共构造配置可由构造 `per_env`、公共 reset 配置及 reset `per_env` 依次覆盖。`random_choice` 从非空 `scheme_ids` 抽样。`enabled` 和外观 `seed` 仅在公共构造配置设置。局部 reset 接受严格递增的环境编号，并省略 reset `seed`。原生状态恢复与外观覆盖分别调用。

两条配置在原生 reset 前完成所选环境的请求校验，材质、随机流、方案与回合记录分别维护。每条记录包含环境、回合、方案和目录版本。`original` 恢复该环境的原生材质，键盘装饰边同时恢复原始贴图像素。

## 模型绑定与独立预览

[笔记本绑定](../../assets/appearance/objects/office_desk/laptop/) 分开使用屏框和键帽的原生视觉记录。内置键帽的正面和反向绕序面同时保留，屏幕图像、触控板、底座和转轴沿用源资产。[独立键盘绑定](../../assets/appearance/objects/office_desk/keyboard/) 保留每个可动键的字标轮廓、采样、UV、关节与目标键提示。主键区和功能键区分别使用当前环境的私有贴图，沿用原生字标图像及其明暗关系。`original` 还原逐字节原生像素。装饰边复用 [原 UV 安全分区](../../assets/appearance/objects/office_desk/keyboard/key_uv_protection.json)。正式任务沿用既定碰撞、质量、关节和成功条件。

下列预览只加载键帽的原生视觉记录，可以独立查看键帽排列和材质。将 `--object laptop` 替换为 `--object keyboard` 可以检查独立键盘。两步输出分别使用新目录。

```powershell
python -B tools/variation/render_office_devices_preview.py --object laptop --keycaps-only `
    --native-off --approved-render --output outputs/laptop_keycaps_native
python -B tools/variation/render_office_devices_preview.py --object laptop --keycaps-only `
    --native-reference outputs/laptop_keycaps_native --approved-render --output outputs/laptop_keycaps_review
```

## 复验

使用 SIPAIR/DexArena 原模型 revision `b197a198fe50f41d70f563cfa7c88d3cc9f528b6` 和对应平台的 [SAPIEN SDK](../../tools/variation/sapien_sdk/README.md)。ClickMouse 使用 `coacd==1.0.14`、`trimesh` 和原模型的五份碰撞缓存。Windows 用 LF 工作树复核源文件哈希。

```powershell
python -B tools/variation/check_office_devices.py --require-assets
python -B -m unittest discover -s tests -p 'test_office*.py'
$captureCommit = git rev-parse HEAD
$batch = 'outputs/office_realistic'
& ./tools/variation/run_office_expansion.ps1 -Batch $batch -Python $python `
    -SapienRoot $sdk -Artifact $receipt -PhysxGpuDir $physx -GpuLock $gpuLock
& $python -B tools/variation/export_office_expansion.py --batch $batch `
    --artifact $receipt --capture-commit $captureCommit --output outputs/office_realistic_review
```

标准 CUDA 检查分别覆盖三个短任务的全部原版与候选、原生相机、逐套恢复、双向局部 reset 和原物理行为。键帽检查还覆盖两个配置键的单独与组合启用，并记录独立键盘字标以及笔记本正面近景。每任务每环境的全部两两检查使用相同相机与固定种子，复算时要求至少 0.1% 的像素有通道变化超过 8 色级。Linux 在标准 CUDA 作业内使用 SDK 的 `run_linux_check.py --checker office --two-env-memory --approved-runtime`，逐项指定 `--task OpenLaptop`、`--task TypeKeys`、`--task ClickMouse`。Long 与完整机器人策略成功另行验收。

## 本次实测

Windows 的三个短任务均通过标准双环境 CUDA 和 CPU 接口。固定方案逐套恢复原版为零像素差，局部 reset 的未选环境状态和相机保持不变。普通全部候选和独立键帽的无渲染 CPU 动态均逐张量等于各自的关闭外观基线。[任务复算摘要](evidence/office_desk_realistic_v1/summary.json) · [键帽 CPU 动态](evidence/office_desk_realistic_v1/windows-keycaps-cpu.json)

Linux 作业 `135567` 的 Office 阶段通过三个短任务的标准双环境 CUDA。终审独立复算固定相机配对、原版恢复、选中状态读回、未选环境隔离、键盘贴图数据和鼠标五份 CoACD 碰撞缓存，并核对实际加载的 SDK。[Linux 复算与回执](evidence/office_desk_realistic_v1/linux-review.json)

| 实景比较 | 固定相机裁剪 |
|---|---|
| OpenLaptop | [屏框](evidence/office_desk_realistic_v1/OpenLaptop_case_comparison.png) · [内置键帽](evidence/office_desk_realistic_v1/OpenLaptop_keycap_comparison.png) |
| TypeKeys | [壳体与装饰边](evidence/office_desk_realistic_v1/TypeKeys_case_comparison.png) · [可动键帽](evidence/office_desk_realistic_v1/TypeKeys_keycap_comparison.png) |
| ClickMouse | [壳体、按钮与滚轮](evidence/office_desk_realistic_v1/ClickMouse_case_comparison.png) |

两套键帽均通过从源模型只加载键帽的独立预览。任务与预览采集的唯一源码差异是可视化工具保留贴图元数据字典，任务代码和正式检查所用的运行模块字节一致。[独立预览回执](evidence/office_desk_realistic_v1/isolated-preview.json) · [任务与预览输入范围](evidence/office_desk_realistic_v1/source-scopes.json) · [内置键帽](evidence/office_desk_realistic_v1/isolated_keycaps/laptop_comparison.png) · [独立键帽](evidence/office_desk_realistic_v1/isolated_keycaps/keyboard_comparison.png)

[上一版 #27 Windows 归档](evidence/office_desk_expansion_v2/summary.json) · [上一版 #27 Linux 作业](evidence/office_desk_expansion_v2/linux-review.json) · [#16 归档](../../assets/appearance/objects/office_desk/previews/runtime/)
