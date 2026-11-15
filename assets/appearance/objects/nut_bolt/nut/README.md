# 螺母（程序生成）（nut_bolt.nut）

状态：**待适配**。本轮为资料归档，不增加运行能力、材质或UV；没有新仿真验证。

原始角色：可抓取／可旋转装配件。V1资源说明：`六边形分段程序 Actor；另有 threaded_nut_revolute.urdf 资产路径`。

尚无已验收新外观；原UV、材质槽及阶段绑定须在后续适配时针对实际资产核定，不能将静态图册视为加载证明。

## 资料与加载边界

V1对象键：`nut_bolt/nut`；V2对应键：`nut`。代码调查基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8；V1视觉资料HF revision b197a198fe50f41d70f563cfa7c88d3cc9f528b6，此revision只说明调查素材，不保证所有后续运行资产等同。

- visual/collision primitives; free actor plus hidden/parked fixed-root articulation twin

正式任务入口（保留家族区分，不凭同名合并）：NutBoltSeatNut-Sharpa-v1 ; NutBoltTurnNut-Sharpa-v1。

## 原始来源

- [tasks/nut_bolt/nut_bolt_long.py](../../../../../tasks/nut_bolt/nut_bolt_long.py)

原始模型／贴图／第三方字体不复制进本档案。获取方式见[环境与资产说明](../../../../../docs/variation/SETUP.md)，原许可见[资源说明](../../../../../tasks/assets/README.md)。不同家族的apple／plate等未确认共享，分别保留目录。[总索引](../../../README.md)。
