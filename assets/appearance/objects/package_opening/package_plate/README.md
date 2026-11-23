# 接收盘（package_opening.package_plate）

状态：**素材及正式接入已交付，限定证据已查收，待最终合并（PR #9）**。本轮只补CPU映射／索引核对，不新增GPU结论。

原始角色：苹果取出后的接收面。V1资源说明：`RoboCasa/Objaverse plate asset`。

original＋variant_1／variant_2的接入与限定运行证据已提供；尚待最终审阅，不提前计为accepted。模型预览不替代任务证据。

## 资料与加载边界

V1对象键：`package_opening/package_plate`；V2对应键：`package_plate`。代码调查基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8；V1视觉资料HF revision b197a198fe50f41d70f563cfa7c88d3cc9f528b6，此revision只说明调查素材，不保证所有后续运行资产等同。

- kinematic visual/collision actor

正式任务入口（保留家族区分，不凭同名合并）：PackageOpeningExtractApple-Sharpa-v1。

## 原始来源

- [tasks/package_opening/package_opening_long.py](../../../../../tasks/package_opening/package_opening_long.py)

原始模型／贴图／第三方字体不复制进本档案。获取方式见[环境与资产说明](../../../../../docs/variation/SETUP.md)，原许可见[资源说明](../../../../../tasks/assets/README.md)。不同家族的apple／plate等未确认共享，分别保留目录。[总索引](../../../README.md)。


## 本次接入与方案身份

唯一参数源：[运行catalog](../../../../../tasks/assets/variation/package_opening/v1/catalog.json)；[用法和范围](../../../../../docs/variation/PACKAGE_OPENING_APPEARANCE.md)；[请求→recipe→记录／历史图注映射](../../../../../docs/variation/evidence/package_opening/SCHEME_MAPPING.json)。

variant_1→teal_glaze（#245C59）；variant_2→ivory_satin（#EFE0BC）。实际plate_1的Material.392，盘面和盘底共用槽；不能用Meal盘作证。

无数字方案入口；env_idx、材质槽、recipe ID和方案序号分别记录。开包装／取苹果／Long接入及87021限定双环境证据保留；受控成功判定不代表完整机器人轨迹，GPU随机路径未验证。

## 十套扩展候选

原两套保留，新增八套已生成G7真实任务场景预览，待用户审图及后续并行验证；见[十套方案](../../../../../docs/variation/PACKAGE_EXPAND_TO_10.md)。不将新八套标为正式验收通过。
