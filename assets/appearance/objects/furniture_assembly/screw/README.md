# 螺钉（furniture_assembly.screw）

2026-11-17：正式外观接口接入与GPU运行检查已完成，物体总状态待团队审阅；Long未接入。接口、SDK、复现与运行证据见[家族说明](../../../../../docs/variation/FURNITURE_APPEARANCE.md)。

## 方案与部件

唯一参数源：[catalog](variants/v1/catalog.json)；部件对应：[bindings](bindings.json)。original恢复当前任务实例捕获的原生材质；variant_1为深青头部，variant_2为砖红头部。

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
