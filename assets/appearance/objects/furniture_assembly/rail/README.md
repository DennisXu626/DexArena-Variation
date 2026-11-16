# 导轨（furniture_assembly.rail）

两套素材、两个真实短任务初态预览及用户整组外观检查已完成。统一复现、验证范围与人工记录见[家族说明](../../../../../docs/variation/FURNITURE_APPEARANCE.md)。

## 参数与部件

唯一参数源：[catalog](variants/v1/catalog.json)；结构化对应：[bindings](bindings.json)。variant_1为深蓝金属／深蓝槽唇，variant_2为香槟铜金属／深铜槽唇，original恢复实际捕获值。

| 角色 | 源码材质变量 | 部件 | 处理 |
|---|---|---|---|
| metal_body | steel | C形底板、两个竖直侧壁 | 随方案变化 |
| channel_details | dark | 卷唇、底板冲压槽视觉 | 随方案变化，保留明暗对比 |

只绑定env.unwrapped.rail_body，绝不把整个rail articulation或screw_head当作导轨一起改色。V2 rail_screw是复合追溯键，导轨与[螺钉](../screw/README.md)仍为两个逻辑对象。

## 任务表示

| 正式短任务 | 原生表示／实际shape数 |
|---|---|
| InsertRail-Sharpa | 可搬运root；主体3＋细节22＝25，各1part |
| FastenScrew-Sharpa | 固定root；主体3＋细节11＝14，各1part |

InsertRail调用build_slider_rail(show_screw_bosses=False)。原生卷唇／冲压槽循环嵌在两侧壁循环内，因此细节重复两遍；FastenScrew的_add_rail_body只添加一遍。预览保留差异，不修原几何或误计金色boss。

来源：[InsertRail builder](../../../../../tasks/furniture_assembly/furniture_assembly_insert_rail.py)、[FastenScrew builder](../../../../../tasks/furniture_assembly/furniture_assembly_fasten_screw.py)；统一绑定：[furniture_preview_materials.py](../../../../../tools/variation/furniture_preview_materials.py)。Link原始组件经.entity解析为真实Entity，再在指定实体内按原生PBR识别角色。

## 当前证据

[InsertRail近景](../../../furniture_assembly/previews/author_check_20261116/InsertRail/comparison_rail.png) · [FastenScrew近景](../../../furniture_assembly/previews/author_check_20261116/FastenScrew/comparison_rail.png)。

两任务实际绑定、材质、原版恢复与版本身份分别见[InsertRail evidence](../../../furniture_assembly/previews/author_check_20261116/InsertRail/evidence.json)、[FastenScrew evidence](../../../furniture_assembly/previews/author_check_20261116/FastenScrew/evidence.json)及相邻manifest；用户已确认均正常。
