# 板件导向架（furniture_assembly.panel_rack）

两套素材、真实任务初态预览及用户整组外观检查已完成。统一复现、验证范围与人工记录见[家族说明](../../../../../docs/variation/FURNITURE_APPEARANCE.md)。

## 参数与部件

唯一参数源：[catalog](variants/v1/catalog.json)；结构化对应：[bindings](bindings.json)。variant_1为深蓝钢架／深色底板，variant_2为浅灰白钢架／中灰底板，original恢复实际捕获值。

| 角色 | 原生部件 | shape数 | 处理 |
|---|---|---|---|
| body | 两侧直槽壁、两块斜槽口、四根加强筋 | 8 | 随方案变化 |
| plate | 底板 | 1 | 随方案变化 |
| pad | 两片槽内衬垫、四个脚垫 | 6 | 保留 |
| bolt | 八个侧壁螺栓头 | 8 | 保留 |
| decal | 九条黄色警示条 | 9 | 保留 |

实测32个shape／32个part，9个可改、23个保留。五种原生PBR组合互异，仅在rack实体内识别，不依赖全场景颜色或固定序号。

## 任务表示

仅FurnitureAssemblyLayFlatPanel-Sharpa-v1加载rack Actor；它是可重新定位的kinematic工装，源码显式质量1.917kg、5个碰撞shape。斜向槽口具有真实碰撞，保持原样。

InsertRail和FastenScrew短任务没有rack实例，不添加替代物。Long虽复用builder，本包不纳入其运行结论。

来源：[build_panel_rack](../../../../../tasks/furniture_assembly/furniture_assembly_lay_flat_panel.py)；统一绑定：[furniture_preview_materials.py](../../../../../tools/variation/furniture_preview_materials.py)。

## 当前证据

[真实全景](../../../furniture_assembly/previews/author_check_20261116/LayFlatPanel/comparison_task.png) · [导向架近景](../../../furniture_assembly/previews/author_check_20261116/LayFlatPanel/comparison_panel_rack.png)。

[manifest](../../../furniture_assembly/previews/author_check_20261116/LayFlatPanel/manifest.json) · [evidence](../../../furniture_assembly/previews/author_check_20261116/LayFlatPanel/evidence.json)保留实际部件与材质；用户已确认新方案及恢复原版正常，最终反馈见家族说明。
