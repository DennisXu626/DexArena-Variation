# 螺钉（程序／资产细节待核对）（furniture_assembly.screw）

状态：**待适配**。本轮为资料归档，不增加运行能力、材质或UV；没有新仿真验证。

原始角色：可抓取／可旋拧紧固件。V1资源说明：`固定源码 furniture_assembly_fasten_screw.py 的 _add_wing_screw_head_link：翼形旋钮/杆/套筒程序视觉部件`。

V2 rail_screw中的螺钉子部件；具体长／短任务构造和材质尚待外观适配时核定，不因同名推断所有模型相同。

## 资料与加载边界

V1对象键：`furniture_assembly/screw`；V2对应键：`rail_screw`。代码调查基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8；V1视觉资料HF revision b197a198fe50f41d70f563cfa7c88d3cc9f528b6，此revision只说明调查素材，不保证所有后续运行资产等同。

- visual/collision rail with articulated revolute screw

正式任务入口（保留家族区分，不凭同名合并）：FurnitureAssemblyFastenScrew-Sharpa-v1。

## 原始来源

- [tasks/furniture_assembly/furniture_assembly_fasten_screw.py](../../../../../tasks/furniture_assembly/furniture_assembly_fasten_screw.py)

原始模型／贴图／第三方字体不复制进本档案。获取方式见[环境与资产说明](../../../../../docs/variation/SETUP.md)，原许可见[资源说明](../../../../../tasks/assets/README.md)。不同家族的apple／plate等未确认共享，分别保留目录。[总索引](../../../README.md)。
