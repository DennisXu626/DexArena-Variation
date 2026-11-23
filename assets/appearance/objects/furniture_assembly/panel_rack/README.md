# 板件导向架（furniture_assembly.panel_rack）

方案选择、正式接口、复现与验收范围见[家族说明](../../../../../docs/variation/FURNITURE_APPEARANCE.md)。

## 方案与部件

材质参数见 [catalog](variants/v1/catalog.json)，部件角色见 [bindings](bindings.json)。original 恢复本次建场捕获的原生材质。十套候选覆盖粉末涂层、搪瓷漆、镀锌和发黑钢件，主体与承力底板有各自饰面。

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
