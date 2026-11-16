# 板件外观首样例（furniture_assembly.flat_panel）

本对象是同学A的首个外观样例。部件对应、original与两套候选参数、Windows本机单环境真实任务对照及作者自检已完成；**板件及四对象整包用户外观检查均已通过**。这是可供接入的素材／预览工作，不是正式外观接口、A4／A5、全部家具任务或机器人完整任务成功验收。总清单中的待适配状态保持；用户已确认整组正常并授权提交。

## 唯一参数源与方案

[catalog.json](variants/v1/catalog.json) 是本样例的唯一候选参数源，版本 `flat-panel-preview-v1`；不在本说明或绑定表维护第二份候选参数。

| 方案ID | 作用 | 当前状态 |
|---|---|---|
| `original` | 恢复本次实际任务加载后捕获的原生材质；不是一张自制原版纹理 | 基准已捕获；精确恢复自检通过 |
| `ivory_matte` | 浅象牙色、较哑光的板面；槽底、封边及槽边保留明暗区别 | 实际材质与两视角自检通过；单对象人工检查通过 |
| `navy_satin` | 深蓝色、较明显的表面高光；槽底及边界继续可辨 | 实际材质与两视角自检通过；单对象人工检查通过 |

候选只修改主面、槽底／止挡、封边、槽边饰条的渲染颜色、粗糙度和金属度；金属度保持0。标签、条码、原有UV／纹理与specular保留。本轮无新增贴图、UV、字体或视觉／碰撞几何，不重建板件。`roughness` 是视觉表面的粗糙度，不是碰撞摩擦系数。

## 部件对应与修改边界

完整结构化说明见 [bindings.json](bindings.json)，实际shape／part对应见[本次作者自检证据](previews/author_check_20261116/evidence.json)。下表中的英文名是源码材质角色，不冒充SAPIEN材质名称。本次实际绑定22个render shape，每个含1个part；索引仅代表此次任务实例，不能外推其它加载版本。

| 源码角色 | 部件 | 本次shape数量 | 候选方案如何处理 |
|---|---|---|---|
| `face` | 主板面、直槽壁与入口斜块 | 5 | 按方案改变颜色、粗糙度；保留已有纹理等属性 |
| `cut` | 导槽底与封闭止挡 | 2 | 随主色变深，保持槽底和终点可辨 |
| `edge` | 四周封边 | 4 | 随主色变深，保持板件侧边层次 |
| `routed` | 直槽边及喇叭口沿边饰条 | 4 | 随主色变化，保持槽口边界 |
| `label` | 纸标签底 | 1 | 保留本次原生材质 |
| `ink` | 标签上的六根条码条纹 | 6 | 保留本次原生材质 |

这些角色由 `build_drawer_panel` 与 `make_render_material` 生成，板件是Actor，不是带按钮／关节link的外部URDF。槽底、入口、封边和标签的几何全部保留；不修改碰撞、接触材质、质量、惯量、机器人、位姿或任务判定。实际不变项检查的范围以运行证据为准，不能把制作意图写成已经通过物理验收。

## 三个任务中的表示

| 正式短任务 | `env.unwrapped.panel` 的原生表示 | 本样例覆盖 |
|---|---|---|
| `FurnitureAssemblyLayFlatPanel-Sharpa-v1` | 可搬运的动态板件；默认开启 `panel_color_jitter` | 本机单环境、关闭颜色抖动的真实任务初态预览与作者自检完成 |
| `FurnitureAssemblyInsertRail-Sharpa-v1` | `kinematic=True` 的固定装配板件；默认开启 `panel_color_jitter` | 整组预览中真实加载，22个shape及原版恢复自检通过；正式接入待完成 |
| `FurnitureAssemblyFastenScrew-Sharpa-v1` | `kinematic=True` 的固定装配板件；调用自身加载入口 | 整组预览中真实加载，22个shape及原版恢复自检通过；正式接入待完成 |

三个短任务调用同一板件builder，但不能用一个任务的预览替代三个任务的运行验证。Long接口不纳入本样例。前两个任务已有原生颜色抖动，它不是本样例的命名方案随机接口。本次预览使用 `panel_color_jitter=False`、seed=0、`visual_detail=True`；original恢复实际捕获值，不以假定颜色代替。正式接入时由Dennis协调命名方案与原生颜色抖动的关系。

## 板件首样例的真实任务预览与作者自检

2026-11-16在Windows本机完成真实 `FurnitureAssemblyLayFlatPanel-Sharpa-v1` 的单环境预览：`physx_cpu`物理、`sapien_cuda`渲染，Torch 2.6.0+cu124／SAPIEN 3.0.3／ManiSkill 3.0.0b22。完整配置与源码／catalog哈希见[manifest.json](previews/author_check_20261116/manifest.json)。同一次reset后不推进物理，依次应用original与两个候选；同一组初态、相机和光照保持一致。

任务视角复用原 `render_camera` 的全局位姿与投影，使用SAPIEN viewer shader；固定近景拍摄同一站立初态，没有移动或平放板件。两视角均为720×720，近／远裁剪约0.01／100m、垂直视场1rad，位姿写入manifest。画面通过SAPIEN RenderWindow读取到CPU，避开本机Windows的CUDA图像张量读取问题；不声称与 `env.render()` 或观测相机路径像素等价。交互查看器移除了本机选择物体时会崩溃的Transform／Path插件，此处理只在预览脚本内生效。

作者自检结果来自[实际证据](previews/author_check_20261116/evidence.json)：22个shape对应与所有候选参数核对通过；切换三方案时状态、elapsed steps、记录的几何／物理／UV及非板件／受保护材质快照保持；original精确恢复通过。reset后 `env.step()` 次数为0。这是当时板件单对象初态的不变项自检，不是动力学压力、跨任务、并行隔离或A4／A5验证；下文另列后续整组结果。

作者导出的任务视角：[original](previews/author_check_20261116/original_task.png)、[ivory_matte](previews/author_check_20261116/ivory_matte_task.png)、[navy_satin](previews/author_check_20261116/navy_satin_task.png)、[三方案对照](previews/author_check_20261116/comparison_task.png)。

固定近景：[original](previews/author_check_20261116/original_detail.png)、[ivory_matte](previews/author_check_20261116/ivory_matte_detail.png)、[navy_satin](previews/author_check_20261116/navy_satin_detail.png)、[三方案对照](previews/author_check_20261116/comparison_detail.png)。

## 四对象整合后的验证

后续使用统一入口在LayFlatPanel、InsertRail、FastenScrew三个真实任务分别完成整组自检；每个任务实际绑定22个板件shape，和该任务本来存在的导向架／导轨／螺钉一起切换两方案。方案名映射、运行命令及完整结果见[整组交付说明](../../../../../docs/variation/FURNITURE_APPEARANCE.md)与[汇总](../../../furniture_assembly/previews/author_check_20261116/summary.json)。

三任务均通过候选参数逐part读回、同reset状态／几何／物理／UV／关节及受保护材质不变、原生材质精确恢复检查；整组11个固定视角恢复原版后的RGB与初始原版逐像素相同。没有调用reset后的物理步进；这只验证已记录的初态属性，不能替代完整任务回归或跨阶段接入。

板件固定近景对照：[LayFlatPanel](../../../furniture_assembly/previews/author_check_20261116/LayFlatPanel/comparison_flat_panel.png)、[InsertRail](../../../furniture_assembly/previews/author_check_20261116/InsertRail/comparison_flat_panel.png)、[FastenScrew](../../../furniture_assembly/previews/author_check_20261116/FastenScrew/comparison_flat_panel.png)。此前板件单对象人工检查已通过，四对象整组人工检查已由用户确认。

## 复现与用户检查

使用已验证的独立Python环境，从仓库根目录运行；`--output`须指定新目录，避免覆盖已有证据：

```powershell
python tools/variation/render_panel_preview.py --static
python tools/variation/render_panel_preview.py --output outputs/panel_preview/run_001
python tools/variation/render_panel_preview.py --view --scheme original
```

`--static`只解析catalog，不导入仿真；`--output`导出六张方案图、两张比较图、manifest和evidence，原始场景快照留在Git忽略的输出目录。`--view --scheme navy_satin`可直接从深蓝方案开始查看。

用户在真实任务human viewer中检查和自行截图：

1. 按 `1`／`2`／`3` 分别选择original／ivory_matte／navy_satin，按 `V` 在任务与固定近景间切换。
2. 每个视角依次检查三方案：外观能否清楚区分，纸标签与条码是否保留，导槽、止挡和入口轮廓是否仍可辨。
3. 同组截图不拖动镜头、不推进物理。若曾移动镜头，按 `V` 回到一个固定视角后重拍该组三方案，另一视角亦然。
4. 人工截图单列并注明“真实DexArena任务human viewer截图”、视角与方案；保留此次 `author_check_20261116/` 原始证据和哈希，不用人工截图覆盖它们。

**板件单对象的用户外观检查已通过**：浅米白、深蓝及原版恢复均反馈正常，见[人工检查记录](previews/author_check_20261116/human_review.json)。原始 `evidence.json` 的 `screenshots_review=pending_human_review` 保留为作者自检时的状态，后续反馈单独记录。人工截图尚未提供，现有图像来自已记录的真实任务帧导出。四对象整包检查已由用户确认；这些检查不能替代正式接入验收。个人环境、原始大输出和缓存留在Git忽略目录。

## 来源、许可与交接

板件由上游DexArena程序生成，源码基准为本次分支起点 `acd6ba232b8da7a97fd313aa3df8a9f595fd55e0`；官方调查基准仍为 `e7d5c49d079153e77da1ce2bfde16edf67ee7fa8`。V1对象键 `furniture_assembly/flat_panel`、V2对应键 `panel` 保留，旧图册的HF revision只描述旧调查素材，不作为本次程序板件整套运行资产身份。

- [板件builder与LayFlatPanel](../../../../../tasks/furniture_assembly/furniture_assembly_lay_flat_panel.py)、[InsertRail](../../../../../tasks/furniture_assembly/furniture_assembly_insert_rail.py)、[FastenScrew](../../../../../tasks/furniture_assembly/furniture_assembly_fasten_screw.py)。
- 原源码按仓库 [Apache-2.0 LICENSE](../../../../../LICENSE) 和既有署名保留；候选参数为本轮制作，无新增第三方图像或字体。原机器人、桌面等素材仍按各自来源许可使用，见[环境与资源](../../../../../docs/variation/SETUP.md)、[资源说明](../../../../../tasks/assets/README.md)。
- 原木纹为可选 `tasks/assets/textures/wood_albedo.png`、`wood_normal.png`、`wood_roughness.png`；本次manifest核定三文件均不存在，实际捕获的纹理槽为空，预览使用源码原有纯色回退。没有为了换色添加假木纹。
- 交付遵循[本轮分工](../../../../../docs/variation/TEAM_APPEARANCE.md)及[贡献规范](../../../../../CONTRIBUTING.md)：本轮提交部件表、参数、预览和复现资料；Dennis组织正式任务接入、固定／随机选择、回合记录、阶段一致性与A4／A5验收。

已完成：部件源码／实际渲染对应、original捕获与恢复、两套材质、单对象两视角对照、后续三任务整组单环境初态作者自检、复现资料。用户已完成整包检查并授权PR交付。未做：Long、命名方案正式接入、集合随机、每回合记录、并行局部reset、完整物理回归和机器人任务执行。[对象总索引](../../../README.md)保持原状态，待集成验收后统一更新。

最终整组人工确认与提交授权见[人工检查记录](../../../furniture_assembly/previews/author_check_20261116/human_review.json)。原始evidence中的人工待检字段保留为运行时状态，最终反馈单独记录；正式任务接入与A4／A5状态不变。
