# 番茄／球形食材（meal_preparation.tomato）

状态：**待适配**。本轮为资料归档，不增加运行能力、材质或UV；没有新仿真验证。

原始角色：可舀取食材。V1资源说明：`MealPreparation_Assets/robocasa/objaverse/tomato/tomato_2/model.xml（保留原黑色外层材质）`。

尚无已验收新外观；原UV、材质槽及阶段绑定须在后续适配时针对实际资产核定，不能将静态图册视为加载证明。

## 资料与加载边界

V1对象键：`meal_preparation/tomato`；V2对应键：`tomato`。代码调查基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8；V1视觉资料HF revision b197a198fe50f41d70f563cfa7c88d3cc9f528b6，此revision只说明调查素材，不保证所有后续运行资产等同。

- 实际RoboCasa visual/collision actor；不是程序食物默认
- 实际RoboCasa visual/collision actor；本任务经_ScaledFoodAssetsMixin构建spoon/tomato缩放版本

正式任务入口（保留家族区分，不凭同名合并）：MealPreparationPlaceBread-Sharpa-v1 ; MealPreparationScoopTomato-Sharpa-v1。

## 原始来源

- [tasks/meal_preparation/meal_preparation_long.py](../../../../../tasks/meal_preparation/meal_preparation_long.py)

原始模型／贴图／第三方字体不复制进本档案。获取方式见[环境与资产说明](../../../../../docs/variation/SETUP.md)，原许可见[资源说明](../../../../../tasks/assets/README.md)。不同家族的apple／plate等未确认共享，分别保留目录。[总索引](../../../README.md)。
