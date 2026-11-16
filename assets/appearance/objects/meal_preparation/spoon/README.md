# 勺子（meal_preparation.spoon）

状态：**original＋两套候选及正式任务接入已交付，限定技术验收通过，待整合/合并；集成状态见PR8**。

原始角色：可抓取餐具／舀取工具。V1资源说明：`MealPreparation_Assets/robocasa/objaverse/spoon/spoon_16/model.xml＋源码固定尺寸胶套`。

## 资料与加载边界

V1对象键：`meal_preparation/spoon`；V2对应键：`spoon`。代码调查基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8；V1视觉资料HF revision b197a198fe50f41d70f563cfa7c88d3cc9f528b6，此revision只说明调查素材，不保证所有后续运行资产等同。

- 实际RoboCasa visual/collision actor；不是程序食物默认
- 实际RoboCasa visual/collision actor；本任务经_ScaledFoodAssetsMixin构建spoon/tomato缩放版本

正式任务入口（保留家族区分，不凭同名合并）：MealPreparationOpenLunchBox-Sharpa-v1 ; MealPreparationPlaceBread-Sharpa-v1 ; MealPreparationScoopTomato-Sharpa-v1。

## 原始来源

- [tasks/meal_preparation/meal_preparation_long.py](../../../../../tasks/meal_preparation/meal_preparation_long.py)

原始模型／贴图／第三方字体不复制进本档案。获取方式见[环境与资产说明](../../../../../docs/variation/SETUP.md)，原许可见[资源说明](../../../../../tasks/assets/README.md)。不同家族的apple／plate等未确认共享，分别保留目录。[总索引](../../../README.md)。

## 本次外观交付

- 部件与材质绑定。RoboCasa `spoon_16` 的 `wire_140088225` 勺体与代码生成的独立胶囊握套分别绑定。
- 方案。亮银配深蓝握套，或石墨灰配暖橙握套。使用程序材质。 新增 UV 为无。
- 阶段。开盒与放面包使用基础勺子，舀番茄与长任务使用现有短柄表示。
- 对照证据。舀番茄短任务的原版及两套勺子近景，另有长任务双环境握套改色和恢复原版画面。 同组使用相同初态或受控状态、相机和光照，附在交付 PR。

[运行参数目录](../../../../../tasks/assets/variation/meal_preparation/v1/catalog.json)是唯一参数源。[复现说明与验收范围](../../../../../docs/variation/MEAL_APPEARANCE.md)列出任务入口、贴图生成、局部 reset 检查和性能数据。

本轮按对象实际加载阶段覆盖三个 Sharpa 短任务与一个 Sharpa 长任务，默认程序午餐盒。随机方案仅 CPU 选择／记录逻辑复现已核对；真实 GPU 随机路径、更多环境／手型、PartNet 午餐盒及完整机器人长任务成功未测。[PR8-R2证据索引](../../../../../docs/variation/evidence/meal_preparation/PR8-R2.md)列出提交对应与范围；限定技术验收依据[PR8-R2查收审阅](https://github.com/DennisXu626/DexArena-Variation/pull/8#pullrequestreview-5919739591)；当前待整合/合并，集成状态见[PR8](https://github.com/DennisXu626/DexArena-Variation/pull/8)。
