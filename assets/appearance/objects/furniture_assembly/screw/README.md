# 螺钉（furniture_assembly.screw）

方案选择、正式接口、复现与验收范围见[家族说明](../../../../../docs/variation/FURNITURE_APPEARANCE.md)。

## 方案与部件

材质参数见 [catalog](variants/v1/catalog.json)，部件角色见 [bindings](bindings.json)。original 恢复本次建场捕获的原生材质。十套候选的握持面采用工程塑料、锌或镍镀层及耐用搪瓷漆。

仅绑定screw_head link，导轨rail_body独立处理。grip随方案变化，reference完整保留。

| 正式短任务 | grip | reference | 合计 |
|---|---|---|---|
| InsertRail-Sharpa | 原暗色头部：槽底、侧壁、倒角，17个shape | 4个金色顶帽，4个shape | 21 shape／21 part |
| FastenScrew-Sharpa | 轮毂、翼形握条，2个shape | 黄铜杆、原有黄铜方向顶条，2个shape | 4 shape／4 part |

InsertRail的槽内表面随grip变色，保留十字槽视觉／碰撞几何与金色顶帽。FastenScrew的黄铜杆与方向顶条共享原生PBR，合为reference；均保留关节及其余材质字段。

## 任务表示与来源

| 正式短任务 | 原生表示 | 来源 |
|---|---|---|
| InsertRail-Sharpa | 可搬运导轨上的十字凹槽头 | [_add_screw_head_link](../../../../../tasks/furniture_assembly/furniture_assembly_insert_rail.py) |
| FastenScrew-Sharpa | 固定导轨上的翼形头 | [_add_wing_screw_head_link](../../../../../tasks/furniture_assembly/furniture_assembly_fasten_screw.py) |

两种表示均为独立转动子link，按当前任务部件分别绑定与恢复。
