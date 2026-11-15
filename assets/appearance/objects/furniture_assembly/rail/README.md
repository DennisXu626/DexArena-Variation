# 金属导轨（程序生成）（furniture_assembly.rail）

状态：**待适配**。本轮为资料归档，不增加运行能力、材质或UV；没有新仿真验证。

原始角色：待装入的长条部件。V1资源说明：`程序构造几何和 RenderMaterial；具体部件代码入口在 furniture_assembly_insert_rail.py`。

V2 rail_screw同时描述rail与其转动螺钉子部件；与screw分目录记录逻辑对象，不按每条初始化行复制资产。

## 资料与加载边界

V1对象键：`furniture_assembly/rail`；V2对应键：`rail_screw`。代码调查基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8；V1视觉资料HF revision b197a198fe50f41d70f563cfa7c88d3cc9f528b6，此revision只说明调查素材，不保证所有后续运行资产等同。

- visual/collision rail with articulated revolute screw

正式任务入口（保留家族区分，不凭同名合并）：FurnitureAssemblyInsertRail-Sharpa-v1 ; FurnitureAssemblyFastenScrew-Sharpa-v1。

## 原始来源

- [tasks/furniture_assembly/furniture_assembly_insert_rail.py](../../../../../tasks/furniture_assembly/furniture_assembly_insert_rail.py)

原始模型／贴图／第三方字体不复制进本档案。获取方式见[环境与资产说明](../../../../../docs/variation/SETUP.md)，原许可见[资源说明](../../../../../tasks/assets/README.md)。不同家族的apple／plate等未确认共享，分别保留目录。[总索引](../../../README.md)。
