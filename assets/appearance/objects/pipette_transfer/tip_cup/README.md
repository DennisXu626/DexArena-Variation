# 吸头杯（程序生成）（pipette_transfer.tip_cup）

状态：**待适配**。本轮为资料归档，不增加运行能力、材质或UV；没有新仿真验证。

原始角色：吸头／杯状工装。V1资源说明：`pipette_transfer_long.py _build_pipette_stand 中的底部承托圆盘（同支架部件，无独立Actor）`。

这是pipette_stand中的底部程序圆盘视觉部件，无独立Actor；保留图册逻辑部件入口，不复制支架素材。后续适配须结合父支架绑定。

## 资料与加载边界

V1对象键：`pipette_transfer/tip_cup`；V2对应键：`pipette_stand`。代码调查基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8；V1视觉资料HF revision b197a198fe50f41d70f563cfa7c88d3cc9f528b6，此revision只说明调查素材，不保证所有后续运行资产等同。

- kinematic visual/collision actor

正式任务入口（保留家族区分，不凭同名合并）：PipetteTransferAspirateLiquid-Sharpa-v1。

## 原始来源

- [tasks/pipette_transfer/pipette_transfer_long.py](../../../../../tasks/pipette_transfer/pipette_transfer_long.py)

原始模型／贴图／第三方字体不复制进本档案。获取方式见[环境与资产说明](../../../../../docs/variation/SETUP.md)，原许可见[资源说明](../../../../../tasks/assets/README.md)。不同家族的apple／plate等未确认共享，分别保留目录。[总索引](../../../README.md)。
