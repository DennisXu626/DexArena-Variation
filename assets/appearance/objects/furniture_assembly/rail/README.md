# 导轨外观制作（furniture_assembly.rail）

导轨是家具家族的长条装配件。本轮已完成部件对应、两套候选及两个正式短任务的真实单环境初态作者检查。四个家具对象已完成整组用户检查并获授权提交；当前不代表正式接入、A4／A5或任务成功。[对象总索引](../../../README.md)中的待适配状态保持。

## 对象范围与唯一参数源

本逻辑对象只包含当前任务 `env.unwrapped.rail_body` 的视觉部件。它属于带螺钉的articulation，但**不包含另一个 `screw_head` link**；不能遍历整条 `env.unwrapped.rail` 后一起改色。V2的 `rail_screw` 对应两个逻辑对象，导轨与[螺钉档案](../screw/README.md)分别交付，不复制模型。

[catalog.json](variants/v1/catalog.json) 是两套候选的唯一参数源，版本 `furniture-rail-preview-v1`。original恢复本次实际捕获的原生材质；没有自制original纹理。

| 方案ID | 设计 | 当前状态 |
|---|---|---|
| `original` | 原生浅色金属主体与较暗的槽／唇细节 | 按实际捕获值恢复，完整材质与像素恢复检查通过；人工检查已通过 |
| `variant_1` | 深蓝阳极金属效果，槽／唇为更深的蓝色金属 | 真实任务对照已生成；人工检查已通过 |
| `variant_2` | 香槟铜色阳极金属效果，槽／唇为深铜色 | 真实任务对照已生成；人工检查已通过 |

“阳极”只描述视觉设计，不改变接触材料或物理。两套方案只覆盖 `metal_body`、`channel_details` 的base color／roughness／metallic；保留原有纹理、UV、specular及其余渲染属性。没有新增贴图、UV、字体、形状、槽孔或刻度；不改变碰撞、质量、惯量、关节、机器人、初态或成功判定。槽／唇继续保持与主体的颜色、明暗区别。

## 部件对应与两个任务的差异

完整来源与实际检查记录见 [bindings.json](bindings.json)。源码变量 `steel` 对应 `metal_body`，`dark` 对应 `channel_details`。它们通过原生完整PBR三字段组合区分，不按近似形状、单独颜色或猜测材质槽名称绑定。

| 角色 | 部件 | 是否可改 |
|---|---|---|
| `metal_body` | C形导轨底板与两个竖直侧壁 | 可改候选的三项渲染参数 |
| `channel_details` | 两条卷唇与底板上九处冲压槽的视觉细节 | 可改候选的三项渲染参数，保留相对对比 |
| `screw_head` | 同articulation的独立可转螺钉link | 不属于本对象；完全排除在候选绑定之外 |

| 正式短任务 | 原生入口及表示 | 本次实测shape／part数量 |
|---|---|---|
| `FurnitureAssemblyInsertRail-Sharpa-v1` | `build_slider_rail(show_screw_bosses=False)`；可搬运的导轨root link | 主体3；细节22；合计25 shape／25 part，均可改 |
| `FurnitureAssemblyFastenScrew-Sharpa-v1` | `build_wing_screw_rail(kinematic=True)` → `_add_rail_body`；root固定、螺钉独立转动 | 主体3；细节11；合计14 shape／14 part，均可改 |

InsertRail当前源码把“两条卷唇＋九处冲压槽”的添加嵌在两侧壁循环内，细节视觉重复两遍；FastenScrew只添加一遍。这是原加载器的实际差异，预览按任务分支严格检查，不为外观工作修正原几何／缩进。InsertRail另传 `show_screw_bosses=False`，不把builder默认分支里的金色boss误计入本任务导轨。两个任务中的螺钉形状也不同，但应由螺钉档案单独记录。

## 实际预览与验证边界

[furniture_rail_definition.py](../../../../../tools/variation/furniture_rail_definition.py) 向共享预览binder提供两个正式任务的原生PBR签名、部件数与近景目标。只接受单环境、`visual_detail=True` 的已reset任务；从真实Link句柄的 `_objs` 取得SAPIEN Entity，组件通过 `.entity` 解析。不存在或类型不符就报错，不回退到整条articulation或其它对象。近景只改变相机，目标取当前导轨root的world位置，不移动导轨或螺钉。

最终 `author_check_002` 在Windows、两个任务各1环境、seed=0、`physx_cpu`物理／`sapien_cuda`渲染下完成；同一reset、相机、光照比较original／两套候选，reset后未调用env.step。两任务的实际绑定、全部part三字段参数读回、几何／物理／UV／关节限位摩擦驱动／初态快照及所有受保护字段检查通过，完整原版材质恢复一致；每任务四个固定视角的恢复原版RGB均逐值相同，最大差值为0。

| 任务 | 真实对照与检查身份 |
|---|---|
| InsertRail | [任务整体](../../../furniture_assembly/previews/author_check_20261116/InsertRail/comparison_task.png) · [导轨特写](../../../furniture_assembly/previews/author_check_20261116/InsertRail/comparison_rail.png) · [证据](../../../furniture_assembly/previews/author_check_20261116/InsertRail/evidence.json) · [manifest](../../../furniture_assembly/previews/author_check_20261116/InsertRail/manifest.json) |
| FastenScrew | [任务整体](../../../furniture_assembly/previews/author_check_20261116/FastenScrew/comparison_task.png) · [导轨特写](../../../furniture_assembly/previews/author_check_20261116/FastenScrew/comparison_rail.png) · [证据](../../../furniture_assembly/previews/author_check_20261116/FastenScrew/evidence.json) · [manifest](../../../furniture_assembly/previews/author_check_20261116/FastenScrew/manifest.json) |

家族方案会分别按导轨、螺钉、板件各自catalog换色；导轨绑定不直接改螺钉，不能把其它家具对象的授权换色误称为“全部其它物体材质不变”。实际保护比较覆盖所有非家具材质及每对象未授权字段，完整基线快照仅留ignored本地输出。

本对象未新增独立task kwarg、方案随机流、回合记录或并行reset接口。正式集成及A4／A5由Dennis统一组织；单环境素材预览不替代这项验收。复现入口见[家具家族说明](../../../../../docs/variation/FURNITURE_APPEARANCE.md)与[共享预览脚本](../../../../../tools/variation/render_furniture_preview.py)。

## 来源、许可和交接

原生导轨为程序模型，来源为[InsertRail builder](../../../../../tasks/furniture_assembly/furniture_assembly_insert_rail.py) 与[FastenScrew的导轨root builder](../../../../../tasks/furniture_assembly/furniture_assembly_fasten_screw.py)。本次源码参考提交 `acd6ba232b8da7a97fd313aa3df8a9f595fd55e0`，官方调查基准 `e7d5c49d079153e77da1ce2bfde16edf67ee7fa8` 保留；旧V1图册的HF revision不作为本次程序模型整包来源。

原源码保留[Apache-2.0 LICENSE](../../../../../LICENSE)与既有署名。两套候选参数为本轮制作，无新增第三方素材或字体。机器人、桌面等已有资源仍按原来源及许可使用，见[资源说明](../../../../../tasks/assets/README.md)和[环境与资源](../../../../../docs/variation/SETUP.md)。交付与职责遵循[本轮分工](../../../../../docs/variation/TEAM_APPEARANCE.md)及[贡献规范](../../../../../CONTRIBUTING.md)。

交接状态：部件说明、候选参数、两个任务的实际绑定／真实对照／有限不变项作者检查已完成；整组用户视觉检查已完成；正式任务接入、A4／A5、Long及机器人任务执行均未完成。四个家具对象已获用户确认，现进入提交流程。

最终整组人工确认与提交授权见[人工检查记录](../../../furniture_assembly/previews/author_check_20261116/human_review.json)。原始evidence中的人工待检字段保留为运行时状态，最终反馈单独记录；正式任务接入与A4／A5状态不变。
