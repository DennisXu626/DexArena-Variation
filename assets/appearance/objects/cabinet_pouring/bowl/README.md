# 目标碗（cabinet_pouring.bowl）

状态：**PourBeads 短任务实景与工程检查通过，待 Dennis 审图**。原版及 Ocean、Citrus、Violet 使用原模型 UV，在内存中保留碗的明暗和纹样。[对照图、运行用法与验证范围](../../../../../docs/variation/evidence/pouring_bowl_beads/README.md)

原始角色：接收珠子的容器。V1资源说明：`RoboCasa bowl/visual/model_normalized_0.obj`。

M1 两试点未加载该对象。Long 使用原碗，本次外观接入和实测覆盖 PourBeads。

## 资料与加载边界

V1对象键：`cabinet_pouring/bowl`；V2对应键：`bowl`。代码调查基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8；V1视觉资料HF revision b197a198fe50f41d70f563cfa7c88d3cc9f528b6，此revision只说明调查素材，不保证所有后续运行资产等同。

- visual OBJ + collision mesh actor

正式任务入口（保留家族区分，不凭同名合并）：CabinetPouringPourBeads-Sharpa-v1。

## 原始来源

- [tasks/cabinet_pouring/cabinet_pouring_long.py](../../../../../tasks/cabinet_pouring/cabinet_pouring_long.py)

原始模型／贴图／第三方字体不复制进本档案。获取方式见[环境与资产说明](../../../../../docs/variation/SETUP.md)，原许可见[资源说明](../../../../../tasks/assets/README.md)。不同家族的apple／plate等未确认共享，分别保留目录。[总索引](../../../README.md)。
