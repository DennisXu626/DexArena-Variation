# Cabinet Pouring 瓶盖

状态：**已完成试点（继承M2及续篇001验收）**。本轮只归档既有三方案；适配验收仅覆盖CabinetPouringPickBottle-Sharpa-v1与CabinetPouringUnscrewCap-Sharpa-v1，不能据此宣称其它家族或全任务完成。

盖主体及两个既有非对称标记仅改颜色／roughness／metallic。原original-2.obj无UV；没有贴图、新UV或新标记几何，也不为目录齐整创建空textures目录。

## 找到完整资料

- [原版资源、恢复机制与版本](original/README.md)
- [部件／阶段绑定](bindings.json)：cap、cap_fixed、cap_twin对应动态A附着盖／固定B附着盖／自由盖。
- [Ocean材质](variants/v1/ocean/materials.json)、[Citrus材质](variants/v1/citrus/materials.json)、[Violet材质](variants/v1/violet/materials.json)
- [已有任务对照与工程表示图](previews/README.md)
- [配套标签制作脚本与说明](../bottle/authoring/README.md)
- [归档到运行发布映射](../../../runtime_mapping.json)

Ocean／Citrus／Violet是**瓶＋盖配套方案**；对象数据可分开阅读，但现有接口按同一scheme_id成套选择，不支持任意独立混配。同回合所有阶段表示保持方案，切换不重抽。原标签／品牌／红条可替换，必须保留清楚的非对称盖转动参照。

档案是制作／归档入口，现有tasks素材是运行发布副本。两处不是可独立修改的源；后续修改需适配验收后同步并核对，单改一边不算发布完成。本轮运行路径及代码保持不变。[总索引](../../../README.md)。
