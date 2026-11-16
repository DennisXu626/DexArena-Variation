# Furniture Assembly四对象外观交付

2026-11-16。板件、板件导向架、导轨和螺钉的素材、三条真实任务单环境初态预览、作者自检与整组用户检查均已完成；用户确认两候选及恢复原版正常，并授权提交。最终确认见[人工检查记录](../../assets/appearance/furniture_assembly/previews/author_check_20261116/human_review.json)。当前尚未提供正式任务外观接口或完成家族验收。[preview_set.json](../../examples/variation/furniture_assembly/preview_set.json) 是统一方案名和任务对象集合的入口，参数仍只保存在各对象自己的catalog。

## 1. 目标与部件对应

为每个对象保留original，制作两套明显不同的候选；保留原有任务细节与物理定义。相同逻辑对象在不同短任务中的表示分别核定，不额外复制原模型或重建几何。

| 对象 | 实际句柄与可变部件 | 保留项和表示差异 | 详细档案 |
|---|---|---|---|
| 板件 `flat_panel` | `panel` Actor；主面、槽底／止挡、封边和槽口饰条 | 标签、条码、UV／纹理保留；LayFlatPanel动态，另外两任务固定；原生颜色抖动在本预览中关闭 | [板件](../../assets/appearance/objects/furniture_assembly/flat_panel/README.md) |
| 导向架 `panel_rack` | LayFlatPanel的 `rack` Actor；钢制主体与底板 | 橡胶垫、银色螺栓、黄色警示条保留；不向原本没有导向架的任务添加对象 | [导向架](../../assets/appearance/objects/furniture_assembly/panel_rack/README.md) |
| 导轨 `rail` | articulation中的 `rail_body` link；金属主体与卷唇／冲压槽细节 | 排除 `screw_head`；InsertRail与FastenScrew的原生视觉数量不同，分别核定并保留 | [导轨](../../assets/appearance/objects/furniture_assembly/rail/README.md) |
| 螺钉 `screw` | articulation中的 `screw_head` link；头部表面 `grip` | InsertRail修改17个原生暗色头部shape，保留十字槽几何和4个金色端点；FastenScrew修改轮毂／翼条，保留黄铜杆与原有黄铜方向顶条；排除 `rail_body` | [螺钉](../../assets/appearance/objects/furniture_assembly/screw/README.md) |

三条正式短任务的集合如下。预览只使用任务本来存在的对象，不把四件强行放进同一场景；Long与其它家族不在本次范围。

| 统一入口名 | 正式任务ID | 一起切换的对象 |
|---|---|---|
| `LayFlatPanel` | `FurnitureAssemblyLayFlatPanel-Sharpa-v1` | 板件、导向架 |
| `InsertRail` | `FurnitureAssemblyInsertRail-Sharpa-v1` | 板件、导轨、十字头螺钉 |
| `FastenScrew` | `FurnitureAssemblyFastenScrew-Sharpa-v1` | 板件、导轨、翼形螺钉 |

当前可编辑的只是渲染参数，不改变碰撞、质量、惯量、接触材质、关节／驱动、机器人、初态、成功判定或原生视觉几何。本轮同场景初态快照检查通过，仍不能替代完整动力学回归。

## 2. 外观方案与唯一素材来源

统一入口使用 `original`／`variant_1`／`variant_2`。下表按实际catalog读取，家族索引只做名字映射，不复制颜色、粗糙度或金属度数值；修改方案参数时编辑对应唯一catalog。

| 对象及唯一catalog | `variant_1`实际本地ID及设计 | `variant_2`实际本地ID及设计 |
|---|---|---|
| [板件catalog](../../assets/appearance/objects/furniture_assembly/flat_panel/variants/v1/catalog.json) | `ivory_matte`：浅象牙色哑光，保留深浅槽／边界 | `navy_satin`：深蓝色，槽边有更明显表面高光 |
| [导向架catalog](../../assets/appearance/objects/furniture_assembly/panel_rack/variants/v1/catalog.json) | `variant_1`：深蓝钢制主体与更深底板 | `variant_2`：浅灰白主体与中灰底板 |
| [导轨catalog](../../assets/appearance/objects/furniture_assembly/rail/variants/v1/catalog.json) | `variant_1`：深蓝阳极金属效果，较暗槽／唇 | `variant_2`：香槟铜色金属效果，深铜槽／唇 |
| [螺钉catalog](../../assets/appearance/objects/furniture_assembly/screw/variants/v1/catalog.json) | `variant_1`：深青色头部表面 | `variant_2`：砖红色头部表面 |

`original`必须恢复当前真实实例捕获的每部件原生材质，不能按一个常量重画“原版”，也不能用另一任务的原版代替。首包没有新增贴图、UV、模型、字体或第三方图像；候选使用自行制作的标量材质参数，保留未授权变更的原有渲染属性。几何与源码按仓库[LICENSE](../../LICENSE)及既有署名保留，已有机器人、桌面等素材继续遵守[原资源说明](../../tasks/assets/README.md)。

## 3. 真实原版与候选对照证据

本轮实际运行是 `outputs/furniture_preview/author_check_002/{LayFlatPanel,InsertRail,FastenScrew}/`，三个任务各1环境，已全部完成，见[结构化汇总](../../assets/appearance/furniture_assembly/previews/author_check_20261116/summary.json)。原始PNG、比较图、manifest与evidence归档到 `assets/appearance/furniture_assembly/previews/author_check_20261116/{Task}/`；大型 `baseline_scene.json` 留在Git忽略的原输出目录。家族证据位于 `objects/` 之外，不计为新增逻辑对象。

| 任务 | 实测render shape数量 | 原版／两候选真实对照 | 结构化记录 |
|---|---|---|---|
| LayFlatPanel | 板件22、导向架32 | [全景](../../assets/appearance/furniture_assembly/previews/author_check_20261116/LayFlatPanel/comparison_task.png)、[板件](../../assets/appearance/furniture_assembly/previews/author_check_20261116/LayFlatPanel/comparison_flat_panel.png)、[导向架](../../assets/appearance/furniture_assembly/previews/author_check_20261116/LayFlatPanel/comparison_panel_rack.png) | [manifest](../../assets/appearance/furniture_assembly/previews/author_check_20261116/LayFlatPanel/manifest.json)、[evidence](../../assets/appearance/furniture_assembly/previews/author_check_20261116/LayFlatPanel/evidence.json) |
| InsertRail | 板件22、导轨25、螺钉21 | [全景](../../assets/appearance/furniture_assembly/previews/author_check_20261116/InsertRail/comparison_task.png)、[板件](../../assets/appearance/furniture_assembly/previews/author_check_20261116/InsertRail/comparison_flat_panel.png)、[导轨](../../assets/appearance/furniture_assembly/previews/author_check_20261116/InsertRail/comparison_rail.png)、[螺钉](../../assets/appearance/furniture_assembly/previews/author_check_20261116/InsertRail/comparison_screw.png) | [manifest](../../assets/appearance/furniture_assembly/previews/author_check_20261116/InsertRail/manifest.json)、[evidence](../../assets/appearance/furniture_assembly/previews/author_check_20261116/InsertRail/evidence.json) |
| FastenScrew | 板件22、导轨14、螺钉4 | [全景](../../assets/appearance/furniture_assembly/previews/author_check_20261116/FastenScrew/comparison_task.png)、[板件](../../assets/appearance/furniture_assembly/previews/author_check_20261116/FastenScrew/comparison_flat_panel.png)、[导轨](../../assets/appearance/furniture_assembly/previews/author_check_20261116/FastenScrew/comparison_rail.png)、[螺钉](../../assets/appearance/furniture_assembly/previews/author_check_20261116/FastenScrew/comparison_screw.png) | [manifest](../../assets/appearance/furniture_assembly/previews/author_check_20261116/FastenScrew/manifest.json)、[evidence](../../assets/appearance/furniture_assembly/previews/author_check_20261116/FastenScrew/evidence.json) |

每张比较图从左到右为original、variant_1、variant_2；各方案原始PNG和图像哈希保存在相邻记录中。逐任务在同一次reset后切换，不调用 `env.step()`，同组初态、相机和光照保持一致。固定全景使用原生human相机的外参与投影；近景只换相机，不移动物体、平放板件、转动螺钉或构造成功状态。它们是标明对象的补充视角，不冒充原相机输出。

manifest记录了任务、seed、环境版本、未提交实现文件的精确哈希、catalog／家族索引身份、相机和捕获路径；evidence保留实际Entity／shape／part、逐部件材质、保护项、快照摘要及original恢复结果。用户此前检查过板件单对象的两候选与恢复原版，见[原板件档案](../../assets/appearance/objects/furniture_assembly/flat_panel/README.md)；后续整组确认见[最终人工记录](../../assets/appearance/furniture_assembly/previews/author_check_20261116/human_review.json)。原始evidence的pending字段保留运行时状态，不覆盖原图或哈希。

此处参考[PR #8](https://github.com/DennisXu626/DexArena-Variation/pull/8)的五块交付组织方式、结构化证据和精确恢复original的核对方式；本家具包的运行范围与结果单独记录，不继承该PR的GPU、并行或任务判定结论。

提交前已集成main基线 `be63`，15份运行实现文件未变；历史manifest中的 `acd6ba2` 仍表示实际运行当时的基准，保留不改写。

## 4. 复现、来源与实际验证

使用已经可运行本项目的Windows独立Python环境，从仓库根目录启动统一入口；这些是家族预览命令，运行结果需以本轮实际证据为准。输出目录必须是新目录，避免覆盖已有证据。

```powershell
python tools/variation/render_furniture_preview.py --task LayFlatPanel --output outputs/furniture_preview/manual_run_001/LayFlatPanel
python tools/variation/render_furniture_preview.py --task InsertRail --output outputs/furniture_preview/manual_run_001/InsertRail
python tools/variation/render_furniture_preview.py --task FastenScrew --output outputs/furniture_preview/manual_run_001/FastenScrew
```

人工查看与截图，例如：

```powershell
python tools/variation/render_furniture_preview.py --task LayFlatPanel --view --scheme variant_1 --focus panel_rack
python tools/variation/render_furniture_preview.py --task InsertRail --view --scheme original
python tools/variation/render_furniture_preview.py --task FastenScrew --view --scheme variant_2 --focus screw
```

不传 `--focus` 时从固定任务全景开始；可用focus必须属于上表该任务现有对象。按 `1`／`2`／`3`会一起切换当前任务内所有本组对象；focus只控制相机，不表示只改当前近景物体。按 `V`循环全景与该任务各对象的固定近景。

截图时先选定固定视角，不拖镜头、不推进物理，依次拍三个方案，再按V换下一视角。若曾挪过镜头，按V恢复固定视角后重拍完整组。检查标签／条码、导向架垫片／黄条、导轨槽与侧边；InsertRail检查十字槽轮廓和4个保留的金色端点，FastenScrew检查黄铜杆与原有黄铜方向顶条。记录方案可辨性，来源注明“真实DexArena任务human viewer截图”及任务、方案、视角；人工结论单独记录。

实际环境为Windows、Python 3.10.22、Torch 2.6.0+cu124、SAPIEN 3.0.3、ManiSkill 3.0.0b22；三个任务均为1环境、seed=0、`physx_cpu`物理、`sapien_cuda`渲染、`visual_detail=True`。前两个任务显式关闭板件颜色抖动；FastenScrew没有该参数，使用其原生固定底色。颜色经viewer读取到CPU，实际相机与捕获路径已写manifest；不声称与 `env.render()`、观测RGB或其它相机路径像素等价。Windows渲染支持不等于PhysX GPU并行支持，本包没有运行CUDA多环境物理或Linux批量隔离。

三个任务的六项作者检查均通过：实际对象／shape／part绑定、每part候选PBR读回、同reset状态／几何／物理／UV／导轨关节快照保持、非家具及受保护材质保持、完整原生材质描述精确恢复、恢复原版后的像素一致。共11个固定视角的恢复图与原图逐值相同，最大像素差均0；三个任务reset后均无物理步进。这些是同一初态的有限作者检查，不是完整物理回归、任务判定或A4／A5验收。源码及素材身份以各manifest的文件哈希为准，来源与许可见四对象档案及[SETUP](SETUP.md)。

## 5. 交接状态与剩余问题

交付按“素材完成／预览完成／人工检查完成／正式接入完成”分别记录。四对象素材、三任务真实预览、结构化证据及有限作者自检已完成；板件先前单对象检查已完成。**新的四对象整组用户检查已完成，用户已明确授权提交本Furniture Assembly素材包**；正式接入状态保持未完成。

后续正式任务kwarg、固定／随机选择、每env回合记录、跨任务／阶段一致性、Linux多环境局部reset与A4／A5由Dennis统一组织。当前没有Long运行、动力学／成功判定完整回归、真实机器人抓放／旋拧成功、随机流复现、其它手型或大规模性能结论。原对象总索引和[能力清单](STATUS.md)不因素材文件增加而自动改成已验收。

检查通过后的PR可以按本文五块提供对象／部件表、两方案、实际任务图片、复现与结构化证据、剩余问题；保留原版恢复核对结果。只提交明确代码、配置、小素材与精简证据，不提交个人路径、凭据、原模型包、大型快照、缓存、录像或环境。流程和职责遵循[TEAM_APPEARANCE](TEAM_APPEARANCE.md)、[CONTRIBUTING](../../CONTRIBUTING.md)及仓库[PR模板](../../.github/PULL_REQUEST_TEMPLATE.md)。
