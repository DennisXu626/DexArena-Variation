# 盘子（meal_preparation.plate）

状态：**两套外观与任务证据已制作，等待 Dennis PR 审阅**。

原始角色：食材承托面。V1资源说明：`MealPreparation_Assets/robocasa/objaverse/plate/plate_0/model.xml`。

## 资料与加载边界

V1对象键：`meal_preparation/plate`；V2对应键：`meal_plate`。代码调查基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8；V1视觉资料HF revision b197a198fe50f41d70f563cfa7c88d3cc9f528b6，此revision只说明调查素材，不保证所有后续运行资产等同。

- RoboCasa actor visual/collision，明确body_type='static'；非procedural plate默认

正式任务入口（保留家族区分，不凭同名合并）：MealPreparationPlaceBread-Sharpa-v1 ; MealPreparationScoopTomato-Sharpa-v1。

## 原始来源

- [tasks/meal_preparation/meal_preparation_long.py](../../../../../tasks/meal_preparation/meal_preparation_long.py)

原始模型／贴图／第三方字体不复制进本档案。获取方式见[环境与资产说明](../../../../../docs/variation/SETUP.md)，原许可见[资源说明](../../../../../tasks/assets/README.md)。不同家族的apple／plate等未确认共享，分别保留目录。[总索引](../../../README.md)。

## 本次外观交付

- 部件与材质绑定。RoboCasa `plate_0` 的 `plate_top` 和 `plate_bottom` 分别绑定。
- 方案。钴蓝亮釉与浅灰蓝盘底，或暖白釉配墨绿盘沿。盘沿使用原 UV 生成图案。 新增 UV 为无。
- 阶段。放面包、舀番茄和完整长任务中的静态接收盘。开盒短任务不加载盘子。
- 对照证据。放面包短任务的原版及两套盘面近景。 同组使用相同初态或受控状态、相机和光照，附在交付 PR。

[运行参数目录](../../../../../tasks/assets/variation/meal_preparation/v1/catalog.json)是唯一参数源。[复现说明与验收范围](../../../../../docs/variation/MEAL_APPEARANCE.md)列出任务入口、贴图生成、局部 reset 检查和性能数据。
