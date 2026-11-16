# 螺钉（furniture_assembly.screw）

两套素材、两个真实短任务初态预览及用户整组外观检查已完成。统一复现、验证范围与人工记录见[家族说明](../../../../../docs/variation/FURNITURE_APPEARANCE.md)。

## 参数与部件

唯一参数源：[catalog](variants/v1/catalog.json)；结构化对应：[bindings](bindings.json)。variant_1为深青头部，variant_2为砖红头部；original按当前任务实例恢复，不能跨表示套用原版。

只绑定screw_head link，排除rail_body。两任务共有grip可改、reference完整保留，但角色对应的原生材质与形状不同。

| 正式短任务 | grip | reference | 实测合计 |
|---|---|---|---|
| InsertRail-Sharpa | 17个原暗色头部shape：槽底、侧壁、倒角 | 4个金色顶帽 | 21 shape／21 part |
| FastenScrew-Sharpa | 轮毂、翼形握条 | 黄铜杆、原有黄铜方向顶条 | 4 shape／4 part |

InsertRail包含槽内表面的17个grip随方案变色；保留的是十字槽视觉／碰撞几何和4金色顶帽，不声称原暗色槽材质不变。用户已确认槽口与头部外观正常。

FastenScrew黄铜杆与方向顶条原生PBR相同，合为一个保留角色，不伪称独立可编辑槽或断言其非对称性。用户已确认两方案及恢复原版正常。

## 原生表示

InsertRail的_add_screw_head_link生成十字凹槽头，挂在可搬运导轨上；FastenScrew的_add_wing_screw_head_link生成翼形头，挂在固定导轨上。两者均有独立转动子link，预览不转动关节。

来源：[InsertRail](../../../../../tasks/furniture_assembly/furniture_assembly_insert_rail.py)、[FastenScrew](../../../../../tasks/furniture_assembly/furniture_assembly_fasten_screw.py)；统一绑定：[furniture_preview_materials.py](../../../../../tools/variation/furniture_preview_materials.py)。

## 当前证据

[十字头近景](../../../furniture_assembly/previews/author_check_20261116/InsertRail/comparison_screw.png) · [翼形头近景](../../../furniture_assembly/previews/author_check_20261116/FastenScrew/comparison_screw.png)。

[InsertRail evidence](../../../furniture_assembly/previews/author_check_20261116/InsertRail/evidence.json) · [FastenScrew evidence](../../../furniture_assembly/previews/author_check_20261116/FastenScrew/evidence.json)记录逐部件材质、原版恢复与相邻manifest身份；用户确认见家族说明。
