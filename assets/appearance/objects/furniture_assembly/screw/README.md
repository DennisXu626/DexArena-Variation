# 家具螺钉外观样例（furniture_assembly.screw）

状态：**两个真实任务的单环境初态作者检查完成，整组人工检查已由用户确认**。本对象与板件、支架、导轨一起交付家具家族首批样例；此处只覆盖两个正式短任务中的 `screw_head`，不修改 `rail_body`。对象总清单保持待适配，不宣称正式外观接口、A4／A5、关节运动或机器人完整任务成功。用户已确认整组正常并授权提交。

## 唯一参数源

[catalog.json](variants/v1/catalog.json) 是本对象唯一候选参数源，版本 `furniture-screw-preview-v1`，范围为素材与单环境初态预览。`original` 恢复实际任务实例捕获的原生材质；`variant_1` 为深青色头部，`variant_2` 为砖红色头部。两个候选只覆盖 `grip` 的颜色、粗糙度与金属度，其它渲染属性、原UV／纹理与全部几何保留。没有新增模型、纹理、UV、字体或外部素材。

两任务的头部形态和原生材质不同，不能把一套原版参数套到另一个任务。候选共用语义角色 `grip`：InsertRail 中是17个原暗色螺头表面，包含槽内底面、侧壁与倒角；FastenScrew 中为圆轮毂与翼形握持条。保留角色统一为 `reference`：前者为4个金色顶帽，后者为黄铜杆与原有黄铜方向顶条。两任务的角色原生PBR值和数量分别定义，详见 [bindings.json](bindings.json)。

## 两种实际源码表示

| 任务 | 螺钉形态与来源 | 本次实测shape／part数量 | 处理 |
|---|---|---|---|
| `FurnitureAssemblyInsertRail-Sharpa-v1` | `_add_screw_head_link` 生成真实十字凹槽头；它是导轨的 `screw_head` 转动子link | `grip`：17个原暗色槽底、侧壁与倒角；`reference`：4个金色顶帽 | 17个螺头表面随方案变色，包含槽内表面；保留十字凹槽形状及4个原金色顶帽，当前映射真实新图已保存，槽的可辨性已由用户确认 |
| `FurnitureAssemblyFastenScrew-Sharpa-v1` | `_add_wing_screw_head_link` 独立生成翼形头；不是前一任务的十字头 | `grip`：2个轮毂／翼条；`reference`：2个黄铜杆／顶条 | 仅改轮毂与翼条；杆及金色转动参照完整保留 |

最终 `author_check_002` 已实测上表的两种表示：InsertRail为**21 shape／21 part，17个grip可改、4个金色reference保留**；FastenScrew为**4 shape／4 part，2个grip可改、2个reference保留**。实际每shape／part与原生PBR记录在结构化证据中，观察索引只描述该实例，不能当固定绑定规则。InsertRail 的槽内材质随 `grip` 改色，不能再称原暗槽材质保持；保留的是原十字凹槽的视觉／碰撞几何与金色顶帽，已在本轮真实任务新图中呈现，用户已确认槽口、深度和头部轮廓正常。FastenScrew 的杆和顶条使用同一个原生黄铜材质，PBR三字段完全相同，因此在按材质匹配的统一绑定器中合为 `reference`，不把它们伪称为独立可编辑材质槽。原有黄铜方向顶条不新增、删除或改成均匀头色；静态源码不证明其非对称性，实际外观已结合真实图像经用户确认，不把静帧说成已经执行旋拧。

## 应用和复现边界

[furniture_screw_definition.py](../../../../../tools/variation/furniture_screw_definition.py) 只读取实际任务的 `env.unwrapped.screw_head`，将 `_objs` 中的组件转换为其真实 `sapien.Entity`，并返回当前表示的原生角色、预期数量及固定近景参考。它不重建物体、不单独运行仿真、不绑定或修改材质，也不改变任务初始化。

由统一家具预览入口执行实际绑定：在目标link中用原生PBR值识别角色，核对shape数量，记录实际几何／pose／part对应，应用当前任务中存在的可编辑角色。必须保留 `rail_body`、其它对象、槽口、关节限位、摩擦／驱动、碰撞、质量、惯量、初态和成功判定。`original` 依实际捕获值恢复，不能使用另一任务的原版或统一金色替代。

本轮归档的是当前17个grip／4个金色reference映射的最终 `author_check_002`，不沿用旧头部映射图片。Windows下两任务各1环境、seed=0、`physx_cpu`物理／`sapien_cuda`渲染，同一reset、相机、光照比较original／两个候选，reset后未调用env.step。全部part参数读回与几何／物理／UV／关节限位摩擦驱动／初态／受保护字段快照检查通过；完整材质恢复精确一致，两个任务各四个固定视角恢复原版后的RGB逐值相同、最大差值0。未为展示槽口或翼条而转动关节、移动导轨或改物理。InsertRail 的补充近景改得稍近且偏顶部，以同时检查头部颜色与十字形槽；物体、关节和任务原相机保持原样。实际材质和原版恢复检查已完成；用户已确认槽口、头部轮廓和金色参照正常。

| 任务 | 当前映射的真实对照与身份 |
|---|---|
| InsertRail | [任务整体](../../../furniture_assembly/previews/author_check_20261116/InsertRail/comparison_task.png) · [螺钉特写](../../../furniture_assembly/previews/author_check_20261116/InsertRail/comparison_screw.png) · [证据](../../../furniture_assembly/previews/author_check_20261116/InsertRail/evidence.json) · [manifest](../../../furniture_assembly/previews/author_check_20261116/InsertRail/manifest.json) |
| FastenScrew | [任务整体](../../../furniture_assembly/previews/author_check_20261116/FastenScrew/comparison_task.png) · [螺钉特写](../../../furniture_assembly/previews/author_check_20261116/FastenScrew/comparison_screw.png) · [证据](../../../furniture_assembly/previews/author_check_20261116/FastenScrew/evidence.json) · [manifest](../../../furniture_assembly/previews/author_check_20261116/FastenScrew/manifest.json) |

图片由真实SAPIEN任务画面CPU读回，完整基线仅留ignored本地输出。共享家族方案分别应用各对象catalog，螺钉绑定自身不写导轨；保护检查针对所有非家具材质及各对象未授权字段。复现入口见[家具家族说明](../../../../../docs/variation/FURNITURE_APPEARANCE.md)。单环境静帧作者检查不代表旋拧执行、关节运动回归、并行局部reset或A4／A5。

## 来源与交接

- 原生程序几何：[InsertRail](../../../../../tasks/furniture_assembly/furniture_assembly_insert_rail.py) 与 [FastenScrew](../../../../../tasks/furniture_assembly/furniture_assembly_fasten_screw.py)。两表示分别读取各自builder，Long不在本样例中。
- 材质工厂来自[板件任务的 `make_render_material`](../../../../../tasks/furniture_assembly/furniture_assembly_lay_flat_panel.py)。原源码与署名按仓库 [Apache-2.0 LICENSE](../../../../../LICENSE) 保留；本轮候选参数为自行制作，没有新增第三方图像或字体。原场景及机器人素材仍按[资源说明](../../../../../tasks/assets/README.md)和[环境说明](../../../../../docs/variation/SETUP.md)获取。
- V1对象键 `furniture_assembly/screw`、V2逻辑键 `rail_screw` 保留；旧调查HF revision只用于来源追溯，不证明本轮实际运行资产版本一致。
- 素材、预览、人工检查和正式接入分别记录。Dennis统一组织正式配置、回合记录、跨阶段一致性和A4／A5验收；本组素材、真实初态预览与有限作者检查已完成，整组人工检查已由用户确认，遵循[本轮分工](../../../../../docs/variation/TEAM_APPEARANCE.md)及[贡献规范](../../../../../CONTRIBUTING.md)。[对象总索引](../../../README.md)状态保持。

最终整组人工确认与提交授权见[人工检查记录](../../../furniture_assembly/previews/author_check_20261116/human_review.json)。原始evidence中的人工待检字段保留为运行时状态，最终反馈单独记录；正式任务接入与A4／A5状态不变。
