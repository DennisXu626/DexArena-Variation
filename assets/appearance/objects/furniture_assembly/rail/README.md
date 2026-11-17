# 导轨（furniture_assembly.rail）

2026-11-17：正式外观接口接入与GPU运行检查已完成，物体总状态待团队审阅；Long未接入。接口、SDK、复现与运行证据见[家族说明](../../../../../docs/variation/FURNITURE_APPEARANCE.md)。

## 方案与部件

唯一参数源：[catalog](variants/v1/catalog.json)；部件对应：[bindings](bindings.json)。original恢复当前实例捕获的原生材质；variant_1为深蓝金属／深蓝槽唇，variant_2为香槟铜金属／深铜槽唇。

| 角色 | 源码材质 | 部件 | InsertRail／FastenScrew shape数 |
|---|---|---|---|
| metal_body | steel | C形底板、两个竖直侧壁 | 3／3 |
| channel_details | dark | 卷唇、底板冲压槽视觉 | 22／11 |

两角色随方案变化并保持明暗对比。仅绑定rail_body link；[screw_head](../screw/README.md)独立处理，保留槽孔几何、关节及其余材质字段。

## 任务表示与来源

| 正式短任务 | 原生表示／总shape数 | 来源 |
|---|---|---|
| InsertRail-Sharpa | 可搬运root；25，各1part | [build_slider_rail](../../../../../tasks/furniture_assembly/furniture_assembly_insert_rail.py) |
| FastenScrew-Sharpa | 固定root；14，各1part | [build_wing_screw_rail／_add_rail_body](../../../../../tasks/furniture_assembly/furniture_assembly_fasten_screw.py) |

InsertRail使用show_screw_bosses=False，卷唇／冲压槽循环在两侧壁内重复两遍；FastenScrew仅添加一遍，均保留各自原生几何。
