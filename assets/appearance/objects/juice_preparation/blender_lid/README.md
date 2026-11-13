# 搅拌机盖（juice_preparation.blender_lid）

状态：**待适配**。本轮为资料归档，不增加运行能力、材质或UV；没有新仿真验证。

原始角色：可抓取／放置部件。V1资源说明：`assets/task_object_meshes/juice/Blender023_Lid`。

独立lid与PressButton合入blender的盖视觉存在阶段差别；后续同逻辑盖适配须覆盖实际加载分支，不给integrated_blender_top重复建素材。

## 资料与加载边界

V1对象键：`juice_preparation/blender_lid`；V2对应键：`blender_lid, integrated_blender_top`。代码调查基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8；V1视觉资料HF revision b197a198fe50f41d70f563cfa7c88d3cc9f528b6，此revision只说明调查素材，不保证所有后续运行资产等同。

- visual/collision dynamic rigid actor, separate from blender in PlaceLid
- 只构建base Blender023；未调用PressButton的_integrate_lid_visual_into_blender，也无独立lid actor。外部资产内部button/link若存在则属于blender本体，不另构建本行对象
- 构造时_integrate_lid_visual_into_blender只合并盖视觉到固定模型结构；button为prismatic link，无独立lid actor

正式任务入口（保留家族区分，不凭同名合并）：JuicePreparationPlaceLid-Sharpa-v1。

## 原始来源

- [tasks/juice_preparation/juice_preparation_place_lid.py](../../../../../tasks/juice_preparation/juice_preparation_place_lid.py)

原始模型／贴图／第三方字体不复制进本档案。获取方式见[环境与资产说明](../../../../../docs/variation/SETUP.md)，原许可见[资源说明](../../../../../tasks/assets/README.md)。不同家族的apple／plate等未确认共享，分别保留目录。[总索引](../../../README.md)。
