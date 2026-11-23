# 板件（furniture_assembly.flat_panel）

方案选择、正式接口、复现与验收范围见[家族说明](../../../../../docs/variation/FURNITURE_APPEARANCE.md)。

## 方案与部件

材质参数见 [catalog](variants/v1/catalog.json)，部件角色见 [bindings](bindings.json)。original 恢复本次建场捕获的原生材质。十套候选包含七类木纹和三类人工覆面。家族 variant_1 和 variant_2 沿用原有内部键名 ivory_matte、navy_satin。

| 角色 | 部件 | shape数 | 处理 |
|---|---|---|---|
| face | 主板面、入口斜块 | 5 | 主板面使用材质贴图，入口斜块沿用对应底色 |
| cut | 导槽底、封闭止挡 | 2 | 随方案变化，保持槽底对比 |
| edge | 四周封边 | 4 | 随方案变化 |
| routed | 直槽及喇叭口沿边饰条 | 4 | 随方案变化 |
| label | 纸标签 | 1 | 保留 |
| ink | 六根条码条纹 | 6 | 保留 |

visual_detail=true时合计22个shape，各1个part；保留标签、条码、UV 和原生法线贴图。角色按部件来源识别。

## 任务表示与来源

| 正式短任务 | 原生表示 |
|---|---|
| [LayFlatPanel-Sharpa](../../../../../tasks/furniture_assembly/furniture_assembly_lay_flat_panel.py) | 动态可搬运Actor |
| [InsertRail-Sharpa](../../../../../tasks/furniture_assembly/furniture_assembly_insert_rail.py) | kinematic固定板件 |
| [FastenScrew-Sharpa](../../../../../tasks/furniture_assembly/furniture_assembly_fasten_screw.py) | 自身加载入口构造的kinematic固定板件 |

三者共享[build_drawer_panel](../../../../../tasks/furniture_assembly/furniture_assembly_lay_flat_panel.py)。前两个任务保留默认开启的panel_color_jitter，FastenScrew使用原生固定底色；可选木纹缺失时沿用源码纯色回退。
