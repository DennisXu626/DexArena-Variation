# 螺栓底座／平台（碰撞工装）（nut_bolt.bolt_platform）

状态：**无视觉，不适用皮肤**。本轮为资料归档，不增加运行能力、材质或UV；没有新仿真验证。

原始角色：支撑结构。V1资源说明：`程序／场景支撑 Actor；当前列为碰撞支撑用途`。

V2核对仅有add_cylinder_collision，没有render body；不需要外观预览或新皮肤。

## 资料与加载边界

V1对象键：`nut_bolt/bolt_platform`；V2对应键：`nut_platform`。代码调查基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8；V1视觉资料HF revision b197a198fe50f41d70f563cfa7c88d3cc9f528b6，此revision只说明调查素材，不保证所有后续运行资产等同。

- 仅add_cylinder_collision；没有render body；radius=.024m，half-height=.003m

正式任务入口（保留家族区分，不凭同名合并）：NutBoltSeatNut-Sharpa-v1 ; NutBoltTurnNut-Sharpa-v1。

## 原始来源

- [tasks/nut_bolt/nut_bolt_long.py](../../../../../tasks/nut_bolt/nut_bolt_long.py)

原始模型／贴图／第三方字体不复制进本档案。获取方式见[环境与资产说明](../../../../../docs/variation/SETUP.md)，原许可见[资源说明](../../../../../tasks/assets/README.md)。不同家族的apple／plate等未确认共享，分别保留目录。[总索引](../../../README.md)。
