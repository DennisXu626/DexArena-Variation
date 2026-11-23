# Office Desk 外观

OpenLaptop、TypeKeys 和 ClickMouse 各支持 original 加十套候选，默认关闭外观。原有两套候选保留，三项共同追加 `variant_3` 至 `variant_10`。

## 选择与记录

各对象 catalog 保存材质参数，设备运行索引保存公开 ID 到材质方案的映射。下表每列标出实际配置键和材质角色，每格依次给出公开 `scheme_id`、材质方案和原生展示相机实景链接。 [笔记本 catalog](../../assets/appearance/objects/office_desk/laptop/catalog.json) · [键盘 catalog](../../assets/appearance/objects/office_desk/keyboard/catalog.json) · [鼠标 catalog](../../tasks/assets/variation/office_desk/mouse_101408/v1/catalog.json) · [设备运行索引](../../tasks/assets/variation/office_desk/devices/v1/catalog.json)

| 饰面 | OpenLaptop · `office_devices_appearance` · `bezel` | TypeKeys · `office_devices_appearance` · `shell` 与 `shell_strip` | ClickMouse · `mouse_appearance` · `shell`、`buttons`、`wheel` |
|---|---|---|---|
| 原版 | `original` → [原生材质](evidence/office_desk_expansion_v2/OpenLaptop/original_human_env0.png) | `original` → [原生材质](evidence/office_desk_expansion_v2/TypeKeys/original_human_env0.png) | `original` → [原生材质](evidence/office_desk_expansion_v2/ClickMouse/original_human_env0.png) |
| 候选 1 | `variant_1` → [`terracotta_matte`](evidence/office_desk_expansion_v2/OpenLaptop/variant_1_human_env0.png) | `variant_1` → [`ochre_matte`](evidence/office_desk_expansion_v2/TypeKeys/variant_1_human_env0.png) | `ivory_matte` → [`ivory_matte`](evidence/office_desk_expansion_v2/ClickMouse/ivory_matte_human_env0.png) |
| 候选 2 | `variant_2` → [`petrol_satin`](evidence/office_desk_expansion_v2/OpenLaptop/variant_2_human_env0.png) | `variant_2` → [`indigo_satin`](evidence/office_desk_expansion_v2/TypeKeys/variant_2_human_env0.png) | `navy_satin` → [`navy_satin`](evidence/office_desk_expansion_v2/ClickMouse/navy_satin_human_env0.png) |
| 朱红 | `variant_3` → [`variant_3`](evidence/office_desk_expansion_v2/OpenLaptop/variant_3_human_env0.png) | `variant_3` → [`variant_3`](evidence/office_desk_expansion_v2/TypeKeys/variant_3_human_env0.png) | `variant_3` → [`variant_3`](evidence/office_desk_expansion_v2/ClickMouse/variant_3_human_env0.png) |
| 柠檬黄 | `variant_4` → [`variant_4`](evidence/office_desk_expansion_v2/OpenLaptop/variant_4_human_env0.png) | `variant_4` → [`variant_4`](evidence/office_desk_expansion_v2/TypeKeys/variant_4_human_env0.png) | `variant_4` → [`variant_4`](evidence/office_desk_expansion_v2/ClickMouse/variant_4_human_env0.png) |
| 薄荷绿 | `variant_5` → [`variant_5`](evidence/office_desk_expansion_v2/OpenLaptop/variant_5_human_env0.png) | `variant_5` → [`variant_5`](evidence/office_desk_expansion_v2/TypeKeys/variant_5_human_env0.png) | `variant_5` → [`variant_5`](evidence/office_desk_expansion_v2/ClickMouse/variant_5_human_env0.png) |
| 松绿 | `variant_6` → [`variant_6`](evidence/office_desk_expansion_v2/OpenLaptop/variant_6_human_env0.png) | `variant_6` → [`variant_6`](evidence/office_desk_expansion_v2/TypeKeys/variant_6_human_env0.png) | `variant_6` → [`variant_6`](evidence/office_desk_expansion_v2/ClickMouse/variant_6_human_env0.png) |
| 钴蓝 | `variant_7` → [`variant_7`](evidence/office_desk_expansion_v2/OpenLaptop/variant_7_human_env0.png) | `variant_7` → [`variant_7`](evidence/office_desk_expansion_v2/TypeKeys/variant_7_human_env0.png) | `variant_7` → [`variant_7`](evidence/office_desk_expansion_v2/ClickMouse/variant_7_human_env0.png) |
| 紫罗兰 | `variant_8` → [`variant_8`](evidence/office_desk_expansion_v2/OpenLaptop/variant_8_human_env0.png) | `variant_8` → [`variant_8`](evidence/office_desk_expansion_v2/TypeKeys/variant_8_human_env0.png) | `variant_8` → [`variant_8`](evidence/office_desk_expansion_v2/ClickMouse/variant_8_human_env0.png) |
| 玫瑰粉 | `variant_9` → [`variant_9`](evidence/office_desk_expansion_v2/OpenLaptop/variant_9_human_env0.png) | `variant_9` → [`variant_9`](evidence/office_desk_expansion_v2/TypeKeys/variant_9_human_env0.png) | `variant_9` → [`variant_9`](evidence/office_desk_expansion_v2/ClickMouse/variant_9_human_env0.png) |
| 石墨灰（笔记本）／瓷白（键盘、鼠标） | `variant_10` → [`variant_10`](evidence/office_desk_expansion_v2/OpenLaptop/variant_10_human_env0.png) | `variant_10` → [`variant_10`](evidence/office_desk_expansion_v2/TypeKeys/variant_10_human_env0.png) | `variant_10` → [`variant_10`](evidence/office_desk_expansion_v2/ClickMouse/variant_10_human_env0.png) |

[设备示例](../../examples/variation/office_desk/devices/) · [鼠标示例](../../examples/variation/office_desk/mouse_101408/)

```python
import gymnasium as gym
import tasks
import torch

env = gym.make("OfficeDeskOpenLaptop-Sharpa-v1", num_envs=2,
    sim_backend="physx_cuda", obs_mode="rgb", render_mode="rgb_array",
    office_devices_appearance={"enabled": True, "scheme_id": "variant_3",
        "per_env": {"1": {"scheme_id": "variant_8"}}})
env.reset(seed=7)
env.reset(options={"env_idx": torch.tensor([1], device=env.unwrapped.device),
    "office_devices_appearance": {"scheme_id": "original"}})
```

`random_choice` 从非空 `scheme_ids` 抽样。覆盖顺序为构造公共 → 构造 `per_env` → reset 公共 → reset `per_env`。`enabled` 和外观 `seed` 仅在构造的公共配置中设置。`per_env` 使用规范的环境编号字符串和字典值。传入的 `env_idx` 须严格递增，局部 reset 省略 reset `seed`。状态恢复沿用原生状态恢复路径，同次调用禁止传入外观覆盖。

启用外观时，首次初始化及普通 reset 均在进入原生 reset 前校验每个选中环境的有效模式及方案。随机模式校验完整候选列表。遇到错误时直接报错，原生 reset、任务随机流、状态和材质写入尚未开始。外观关闭时仍校验覆盖格式，任务直接沿用原生外观。

每个环境有独立的私有材质、外观随机流和回合计数。显式选择和渲染均不抽样。回合记录包含 `env_idx`、`episode_index`、`scheme_id` 和 `catalog_version`。

## 原生槽与保护

[笔记本](../../assets/appearance/objects/office_desk/laptop/) 只修改屏框背壳 `new-2.obj/material-0` 的颜色、粗糙度和金属度，保留屏幕、标识与其他槽。[键盘](../../assets/appearance/objects/office_desk/keyboard/) 修改三个无纹理外沿槽，并从原纹理壳体的 502 面中分出 76 个无字壳带面。每个环境为壳带预先绑定原图的私有副本，切换时只上传像素：候选使用目录色，`original` 恢复逐字节相同的原生像素。其余 426 面及 77 个可动键保留原 PBR 和原纹理。目标键映射 `P39/A24/I41/R45/ENTER35` 不变。

[UV 证明](../../assets/appearance/objects/office_desk/keyboard/key_uv_protection.json) 检查连续三角面与双线性纹理采样是否进入键面及其 8 texel 边界，可从原资产重新计算。重新分组保留原三角面、顶点、法线、UV、绕序和变换。双环境下，绿色视觉标记在各自目标键上更新。几何、碰撞、质量、关节及任务成功条件保持原定义。

## 复现与验收边界

准备 SIPAIR/DexArena 原模型 revision `b197a198fe50f41d70f563cfa7c88d3cc9f528b6` 和对应平台的 [SAPIEN SDK](../../tools/variation/sapien_sdk/README.md)。ClickMouse 使用 `coacd==1.0.14`、`trimesh` 和原模型随附的五份碰撞缓存。复核源文件指纹使用 LF 工作树（Windows 可用 `git -c core.autocrlf=false clone`）。

```powershell
python -B tools/variation/check_office_devices.py --require-assets
python -B -m unittest discover -s tests -p 'test_office*.py'
python -B tools/variation/check_static.py
python -B tools/variation/check_appearance_archive.py
$captureCommit = git rev-parse HEAD
$batch = 'outputs/office_expansion_new'
& ./tools/variation/run_office_expansion.ps1 -Batch $batch -Python $python `
    -SapienRoot $sdk -Artifact $receipt -PhysxGpuDir $physx
& $python -B tools/variation/export_office_expansion.py --batch $batch `
    --artifact $receipt --capture-commit $captureCommit --output outputs/office_expansion_review
```

脚本逐项串行执行，`-GpuLock $gpuLock` 复用协调者提供的共享 GPU 锁。使用新的输出目录。正式导出从原始 PNG、PT 和纹理数组复算，记录捕获提交及源码和图片哈希。Linux 在标准 CUDA 作业内用公共 SDK 的 `run_linux_check.py`，选择 `--checker office --two-env-memory --approved-runtime`，逐次指定 `--task OpenLaptop`、`--task TypeKeys`、`--task ClickMouse`。依赖与启动参数见 [SDK 说明](../../tools/variation/sapien_sdk/README.md)。

| 验收项 | 实测结果 |
|---|---|
| CPU 合同与静态 | 23 项合约、源资产与任务 AST、76 面 UV、运行静态、仓库和档案检查通过 |
| Windows CPU | 三个短任务的原生接口通过。39 组动态，共 2,340 控制步、46,800 物理子步，逐步张量与原任务一致 |
| Windows 标准 CUDA | 实际加载 `3.0.3+dexarena.gpu1.wininterop5`。双环境完成 126 次状态读回、6 控制步和 120 物理子步。双向局部 reset 的未选状态与图像不变，逐套恢复 original 的原生相机 RGB 差为 0 |
| Linux 标准 CUDA | 作业 `123860` 从冻结石墨灰版运行三项短任务。126 次选中状态读回、330 组候选对照、200 组原版恢复与 40 组局部相机对照通过 |

固定外观均用种子 7 和原生相机。每任务对每环境的展示相机比较全部 55 对方案，要求至少 0.1% 像素有通道变化超过 8 色级。TypeKeys 额外核对每环境私有纹理句柄、128 份原生纹理数组和两种局部 reset 方向的实际绿色目标提示。ClickMouse 逐份核对 CoACD 加载及缓存。验收覆盖三个短任务。Long、分割图和完整机器人策略成功未验收。

[本地 Windows 复算摘要](evidence/office_desk_expansion_v2/summary.json) · [本地 Windows 正式实景](evidence/office_desk_expansion_v2/) · [Linux 作业与输入身份](evidence/office_desk_expansion_v2/linux-review.json) · [#16 原始归档](../../assets/appearance/objects/office_desk/previews/runtime/)
