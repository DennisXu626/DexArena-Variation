# 目标碗（cabinet_pouring.bowl）

状态：**待适配**。本轮为资料归档，不增加运行能力、材质或UV；没有新仿真验证。

原始角色：接收珠子的容器。V1资源说明：`RoboCasa bowl/visual/model_normalized_0.obj`。

M1两试点未加载，Long／PourBeads家族分支使用；保留待适配，不把试点未加载误写成整个家族无对象。

## 资料与加载边界

V1对象键：`cabinet_pouring/bowl`；V2对应键：`bowl`。代码调查基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8；V1视觉资料HF revision b197a198fe50f41d70f563cfa7c88d3cc9f528b6，此revision只说明调查素材，不保证所有后续运行资产等同。

- visual OBJ + collision mesh actor

正式任务入口（保留家族区分，不凭同名合并）：CabinetPouringPourBeads-Sharpa-v1。

## 原始来源

- [tasks/cabinet_pouring/cabinet_pouring_long.py](../../../../../tasks/cabinet_pouring/cabinet_pouring_long.py)

原始模型／贴图／第三方字体不复制进本档案。获取方式见[环境与资产说明](../../../../../docs/variation/SETUP.md)，原许可见[资源说明](../../../../../tasks/assets/README.md)。不同家族的apple／plate等未确认共享，分别保留目录。[总索引](../../../README.md)。
