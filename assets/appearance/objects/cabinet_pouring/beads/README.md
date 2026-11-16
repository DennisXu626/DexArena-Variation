# 蓝色珠子（程序生成）（cabinet_pouring.beads）

当前状态：**作业88174已运行；参数绑定、物理初态、恢复及限定隔离断言通过，视觉交验仍受阻，待Dennis审验**。柜体／碗预期配色未实现；珠子独立RGB效果未确认。统计仍pending_adaptation，不增加已验收数量。见[实际结果与真实图](../../../../../docs/variation/evidence/cabinet_remaining/README.md)。下文“待验证”描述保留为准备阶段历史，不代表当前尚未运行。

原始角色：倒出的目标颗粒。V1资源说明：`代码创建球体 RenderMaterial`。

M1实际加载16颗程序球体，通常位于闭瓶内；本轮没有新增颗粒材质方案。

## 资料与加载边界

V1对象键：`cabinet_pouring/beads`；V2对应键：`beads`。代码调查基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8；V1视觉资料HF revision b197a198fe50f41d70f563cfa7c88d3cc9f528b6，此revision只说明调查素材，不保证所有后续运行资产等同。

- procedurally generated dynamic particles; collision spheres

正式任务入口（保留家族区分，不凭同名合并）：CabinetPouringPourBeads-Sharpa-v1。

## 原始来源

- [tasks/cabinet_pouring/cabinet_pouring_long.py](../../../../../tasks/cabinet_pouring/cabinet_pouring_long.py)

原始模型／贴图／第三方字体不复制进本档案。获取方式见[环境与资产说明](../../../../../docs/variation/SETUP.md)，原许可见[资源说明](../../../../../tasks/assets/README.md)。不同家族的apple／plate等未确认共享，分别保留目录。[总索引](../../../README.md)。

## 本轮参数与绑定（运行未验证）

particles[i]为原程序球，默认16颗、半径0.004m；所有has_bottle任务均加载，不只倒珠阶段可见。沿用原数量/生成/碰撞/质量及阶段位置关系；仅启用外观时分env调用同一原生球构建helper后合并，以避免显式材质跨env共享。

[完整部件/槽/任务映射](bindings.json)。OpenCabinet仅柜体；PickBottle柜体和珠子；UnscrewCap仅珠子；PourBeads碗和珠子；Long三者原生加载，外观入口已准备但运行/全阶段未验证。缺失对象不做占位。四短任务+Long仅Sharpa列入提案；不能外推其它手型或完整任务成功。

original完整恢复捕获的base_color、base_color_texture、roughness和metallic（其余属性从未修改）。ocean与citrus读取[唯一catalog](../../../../../tasks/assets/variation/cabinet_pouring/v1/catalog.json)的schemes.<ID>.objects.beads；ocean为蓝绿柜/暖白碗/橙珠，citrus为暖木柜/深绿碗/紫珠。violet省略这三对象参数，恢复其原版，不改变原瓶/盖紫色方案。无新贴图、UV或几何，无额外外部素材；原模型/纹理许可仍按上方原渠道，自制标量参数随项目许可。

沿用variation.appearance的固定/集合随机、per_env及局部reset覆盖，不增加任意逐对象组合接口。一次reset选同一方案，所有实际表示复用该选择；original恢复先于新方案写入，未覆盖项不沿用上一回合颜色。材质owner检查拒绝跨env共享；运行隔离尚未证明。初始位姿功能仍只允许原PickBottle/UnscrewCap。

参数可直接复现，无素材制作脚本或新图片需要生成；沿用[配置示例](../../../../../examples/variation/cabinet_pouring/appearance.json)或随机示例，任务与边界见[本轮说明](../../../../../docs/variation/CABINET_REMAINING.md)。素材/接入已准备，CPU检查见说明；真实同seed/相机/光照原版及两候选、切回original、阶段与局部reset对照均待获批短检，不提供假预览。
