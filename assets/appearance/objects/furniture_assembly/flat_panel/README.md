# 板件（furniture_assembly.flat_panel）

方案选择、正式接口、复现与验收范围见[家族说明](../../../../../docs/variation/FURNITURE_APPEARANCE.md)。

## 方案与部件

唯一参数源：[catalog](variants/v1/catalog.json)；部件对应：[bindings](bindings.json)。original恢复当前实例捕获的原生材质；家族variant_1映射ivory_matte（浅象牙哑光），variant_2映射navy_satin（深蓝表面）。

| 角色 | 部件 | shape数 | 处理 |
|---|---|---|---|
| face | 主板面、入口斜块 | 5 | 随方案变化 |
| cut | 导槽底、封闭止挡 | 2 | 随方案变化，保持槽底对比 |
| edge | 四周封边 | 4 | 随方案变化 |
| routed | 直槽及喇叭口沿边饰条 | 4 | 随方案变化 |
| label | 纸标签 | 1 | 保留 |
| ink | 六根条码条纹 | 6 | 保留 |

visual_detail=true时合计22个shape，各1个part；保留标签、条码及其余材质字段。角色按部件来源识别。

## 任务表示与来源

| 正式短任务 | 原生表示 |
|---|---|
| [LayFlatPanel-Sharpa](../../../../../tasks/furniture_assembly/furniture_assembly_lay_flat_panel.py) | 动态可搬运Actor |
| [InsertRail-Sharpa](../../../../../tasks/furniture_assembly/furniture_assembly_insert_rail.py) | kinematic固定板件 |
| [FastenScrew-Sharpa](../../../../../tasks/furniture_assembly/furniture_assembly_fasten_screw.py) | 自身加载入口构造的kinematic固定板件 |

三者共享[build_drawer_panel](../../../../../tasks/furniture_assembly/furniture_assembly_lay_flat_panel.py)。前两个任务保留默认开启的panel_color_jitter，FastenScrew使用原生固定底色；可选木纹缺失时沿用源码纯色回退。
