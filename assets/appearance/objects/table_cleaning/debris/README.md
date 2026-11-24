# 糖块碎屑（table_cleaning.debris）

状态：**待适配**。本轮为资料归档，不增加运行能力、材质或UV；没有新仿真验证。

原始角色：可拾取碎屑目标。V1资源说明：`assets/task_object_meshes/TableClean/robocasa/lightwheel/sugar_cube/SugarCube001/model.xml（视觉group1；scale=2）`。

尚无已验收新外观；原UV、材质槽及阶段绑定须在后续适配时针对实际资产核定，不能将静态图册视为加载证明。

## 资料与加载边界

V1对象键：`table_cleaning/debris`；V2对应键：`debris`。代码调查基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8；V1视觉资料HF revision b197a198fe50f41d70f563cfa7c88d3cc9f528b6，此revision只说明调查素材，不保证所有后续运行资产等同。

- MJCFObject.actor_builder已有convex collision，build_dynamic；源码明确no CoACD；默认3粒scale2、DEBRIS_SIZE=.010，尺寸20mm

正式任务入口（保留家族区分，不凭同名合并）：TableCleaningPickDebris-Sharpa-v1 ; TableCleaningDumpDustpan-Sharpa-v1。

## 原始来源

- [tasks/table_cleaning/table_cleaning_long.py](../../../../../tasks/table_cleaning/table_cleaning_long.py)

原始模型／贴图／第三方字体不复制进本档案。获取方式见[环境与资产说明](../../../../../docs/variation/SETUP.md)，原许可见[资源说明](../../../../../tasks/assets/README.md)。不同家族的apple／plate等未确认共享，分别保留目录。[总索引](../../../README.md)。

## 2026-11-24 十方案实施

用户已确认十套方案，保留 original 与旧 variant_1/2，新增 variant_3–10。
唯一运行参数见 `tasks/assets/variation/table_cleaning/v1/catalog.json`，支持三个 Sharpa 入口。
实现与当前验证范围见[十方案记录](../../../../../docs/variation/TABLE_CLEANING_TEN_VARIANTS.md)。
本节实施状态不将上面的历史“待适配”调查记录当作新增验收证据。
