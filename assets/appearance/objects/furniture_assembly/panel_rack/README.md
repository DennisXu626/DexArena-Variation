# 板件导向架（furniture_assembly.panel_rack）

2026-11-17：正式外观接口接入与GPU运行检查已完成，物体总状态待团队审阅；Long未接入。接口、SDK、复现与运行证据见[家族说明](../../../../../docs/variation/FURNITURE_APPEARANCE.md)。

## 方案与部件

唯一参数源：[catalog](variants/v1/catalog.json)；部件对应：[bindings](bindings.json)。original恢复当前实例捕获的原生材质；variant_1为深蓝钢架／深色底板，variant_2为浅灰白钢架／中灰底板。

| 角色 | 部件 | shape数 | 处理 |
|---|---|---|---|
| body | 两侧直槽壁、两块斜槽口、四根加强筋 | 8 | 随方案变化 |
| plate | 底板 | 1 | 随方案变化 |
| pad | 两片槽内衬垫、四个脚垫 | 6 | 保留 |
| bolt | 八个侧壁螺栓头 | 8 | 保留 |
| decal | 九条黄色警示条 | 9 | 保留 |

visual_detail=true时合计32个shape／32个part，9个可改、23个保留。绑定范围仅rack实体，保留衬垫、脚垫、螺栓、警示条及其余材质字段。

## 任务表示与来源

仅FurnitureAssemblyLayFlatPanel-Sharpa-v1加载rack Actor：可重新定位的kinematic工装，原生质量1.917kg、5个碰撞shape，含斜向槽口碰撞。

来源：[build_panel_rack及任务初始化](../../../../../tasks/furniture_assembly/furniture_assembly_lay_flat_panel.py)。InsertRail与FastenScrew短任务没有rack实例。
