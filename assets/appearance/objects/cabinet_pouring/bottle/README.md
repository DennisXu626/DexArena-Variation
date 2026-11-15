# Cabinet Pouring 瓶身

状态：**已完成试点（继承M2及续篇001验收）**。本轮只归档既有三方案；适配验收仅覆盖CabinetPouringPickBottle-Sharpa-v1与CabinetPouringUnscrewCap-Sharpa-v1，不能据此宣称其它家族或全任务完成。

真实标签PNG位于各方案textures/label.png，材质参数包括瓶身颜色、标签白色乘色、roughness和metallic。沿用原original-3.obj的38个UV顶点，不重展UV、不生成新模型。

## 找到完整资料

- [原版资源、恢复机制与版本](original/README.md)
- [部件／阶段绑定](bindings.json)：source、source_fixed、source_open对应动态A／固定B／开口C。
- [Ocean材质](variants/v1/ocean/materials.json)、[Citrus材质](variants/v1/citrus/materials.json)、[Violet材质](variants/v1/violet/materials.json)
- [已有任务对照与工程表示图](previews/README.md)
- [真实制作脚本与字体说明](authoring/README.md)
- [归档到运行发布映射](../../../runtime_mapping.json)

Ocean／Citrus／Violet是**瓶＋盖配套方案**；对象数据可分开阅读，但现有接口按同一scheme_id成套选择，不支持任意独立混配。同回合所有阶段表示保持方案，切换不重抽。原标签／品牌／红条可替换，必须保留清楚的非对称盖转动参照。

档案是制作／归档入口，现有tasks素材是运行发布副本。两处不是可独立修改的源；后续修改需适配验收后同步并核对，单改一边不算发布完成。本轮运行路径及代码保持不变。[总索引](../../../README.md)。
