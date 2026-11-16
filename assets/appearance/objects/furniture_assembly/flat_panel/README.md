# 板件（furniture_assembly.flat_panel）

两套素材、三个短任务真实初态预览及用户整组外观检查已完成。统一复现、验证范围与人工记录见[家族说明](../../../../../docs/variation/FURNITURE_APPEARANCE.md)。

## 参数与部件

唯一参数源：[catalog](variants/v1/catalog.json)；结构化对应：[bindings](bindings.json)。家族variant_1映射ivory_matte（浅象牙哑光），variant_2映射navy_satin（深蓝表面），original恢复实际捕获值。

| 源码角色 | 部件 | shape数 | 处理 |
|---|---|---|---|
| face | 主板面、入口斜块 | 5 | 随方案变化 |
| cut | 导槽底、封闭止挡 | 2 | 随方案变化，保持槽底对比 |
| edge | 四周封边 | 4 | 随方案变化 |
| routed | 直槽及喇叭口沿边饰条 | 4 | 随方案变化 |
| label | 纸标签 | 1 | 保留 |
| ink | 六根条码条纹 | 6 | 保留 |

22个shape各1个part。角色来自源码变量，不冒充引擎材质名称或固定序号绑定；实际对应见任务evidence。

## 任务表示

| 正式短任务 | 原生表示 |
|---|---|
| LayFlatPanel-Sharpa | 动态可搬运Actor |
| InsertRail-Sharpa | kinematic固定板件 |
| FastenScrew-Sharpa | 自身加载入口构造的kinematic固定板件 |

前两个任务原生panel_color_jitter默认开启，受控预览关闭；FastenScrew使用原生固定底色。三者共享[build_drawer_panel](../../../../../tasks/furniture_assembly/furniture_assembly_lay_flat_panel.py)，但各自加载和初始化分别核定。可选木纹缺失时沿用源码纯色回退，不新增假纹理。

## 当前证据

[LayFlatPanel近景](../../../furniture_assembly/previews/author_check_20261116/LayFlatPanel/comparison_flat_panel.png) · [InsertRail近景](../../../furniture_assembly/previews/author_check_20261116/InsertRail/comparison_flat_panel.png) · [FastenScrew近景](../../../furniture_assembly/previews/author_check_20261116/FastenScrew/comparison_flat_panel.png)。当前manifest／evidence与用户确认统一见[家族归档](../../../furniture_assembly/previews/author_check_20261116/summary.json)。

原先单板件的图片、完整证据和人检仅作[59fb134历史记录](https://github.com/DennisXu626/DexArena-Variation/tree/59fb134f908f037c94caf5a018b1c6f13374caa0/assets/appearance/objects/furniture_assembly/flat_panel/previews/author_check_20261116)保留，不再维护第二套本地预览入口。
