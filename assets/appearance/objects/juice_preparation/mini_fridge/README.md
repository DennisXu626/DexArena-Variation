# 迷你冰箱（juice_preparation.mini_fridge）

状态：**待适配**。本轮为资料归档，不增加运行能力、材质或UV；没有新仿真验证。

原始角色：可动家电／冰箱门。V1资源说明：`assets/task_object_meshes/juice/tabletop_mini_fridge_v1/tabletop_mini_fridge.urdf`。

尚无已验收新外观；原UV、材质槽及阶段绑定须在后续适配时针对实际资产核定，不能将静态图册视为加载证明。

## 资料与加载边界

V1对象键：`juice_preparation/mini_fridge`；V2对应键：`fridge`。代码调查基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8；V1视觉资料HF revision b197a198fe50f41d70f563cfa7c88d3cc9f528b6，此revision只说明调查素材，不保证所有后续运行资产等同。

- URDF articulation visual/collision links

正式任务入口（保留家族区分，不凭同名合并）：JuicePreparationOpenFridge-Sharpa-v1 ; JuicePreparationAppleToBlender-Sharpa-v1 ; JuicePreparationCloseFridge-Sharpa-v1。

## 原始来源

- [tasks/juice_preparation/juice_preparation_long.py](../../../../../tasks/juice_preparation/juice_preparation_long.py)
- [tasks/juice_preparation/juice_preparation_open_fridge.py](../../../../../tasks/juice_preparation/juice_preparation_open_fridge.py)

原始模型／贴图／第三方字体不复制进本档案。获取方式见[环境与资产说明](../../../../../docs/variation/SETUP.md)，原许可见[资源说明](../../../../../tasks/assets/README.md)。不同家族的apple／plate等未确认共享，分别保留目录。[总索引](../../../README.md)。
