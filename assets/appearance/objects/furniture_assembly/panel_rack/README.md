# 板件导向架／装配工装（程序生成）（furniture_assembly.panel_rack）

状态：**真实任务单环境作者检查完成，整组用户检查已完成**。本目录新增 original＋两套材质方案及预览角色定义；未接入正式任务配置、随机选择或回合记录，不改变对象总索引的“待适配”状态。

本体是程序生成的可重定位导向工装，使用一个 **kinematic Actor**，并非关节模型。板件夹在两侧槽壁之间；原代码的斜向槽口也有真实碰撞，不能为了换外观删减。源码给工装设置 1.917 kg 质量；本包不修改它。

唯一候选参数源为 [catalog](variants/v1/catalog.json)，实际部件对应与任务覆盖见 [bindings](bindings.json)。original 从真实实例捕获的原生材质恢复；`variant_1` 为深蓝钢架配深色底板，`variant_2` 为浅灰白钢架配中灰底板。两套均完整保留深色衬垫／脚垫、银色螺栓和黄色警示条。没有新增 UV、贴图、模型或字体，也不制造占位文件。

| 角色 | 原代码部件 | 本次实测 shape／part 数 | 本包处理 |
|---|---|---:|---|
| body | 两侧直槽壁、两块斜槽口、四根外侧加强筋 | 8 | 调整颜色／粗糙度／金属度 |
| plate | 底板 | 1 | 调整颜色／粗糙度／金属度 |
| pad | 两片槽内衬垫、四个橡胶脚垫 | 6 | 完整保留原生材质 |
| bolt | 固定侧壁的八个螺栓头视觉 | 8 | 完整保留原生材质 |
| decal | 底板前沿九条黄色警示条 | 9 | 完整保留原生材质 |

本次在真实 LayFlatPanel 初态实测 **32 个视觉 shape、32 个 part**，其中9个part可改、23个part完整保留，与表中角色数量一致。原源码包含5个碰撞shape，本包不增改碰撞。五类原生 PBR 三字段组合各不相同，可在指定 rack 实体内识别，不靠全场景颜色匹配或固定 shape 序号。衬垫／脚垫共用一个 pad 角色，不重复制作素材。

## 资料与加载边界

V1对象键：`furniture_assembly/panel_rack`；V2对应键：`rack`。代码调查基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8；V1视觉资料HF revision b197a198fe50f41d70f563cfa7c88d3cc9f528b6，此revision只说明调查素材，不保证所有后续运行资产等同。

- `FurnitureAssemblyLayFlatPanel-Sharpa-v1`：真实加载 `env.unwrapped.rack`；本包预览只覆盖这个正式短任务的单环境初态。
- `FurnitureAssemblyInsertRail-Sharpa-v1`、`FurnitureAssemblyFastenScrew-Sharpa-v1`：各自源码加载路径**没有 rack 实例**，不是需要重复应用本包的表示。
- Long 源码也使用同一 builder，但不纳入本轮预览运行结论。

预览入口定义：[furniture_rack_definition.py](../../../../../tools/variation/furniture_rack_definition.py)。它只返回实际实体、角色原生签名、预计数量及特写取景参考；共享预览工具负责检查实际绑定、应用候选、原版恢复和记录证据。需要 `visual_detail=True`，不提供正式任务 kwarg，不修改任务 loader。

最终 `author_check_002` 已在 Windows、1环境、seed=0、`visual_detail=True`、`physx_cpu`物理／`sapien_cuda`渲染下完成。original／两套候选使用同一reset、相机和光照，reset后未调用env.step。实际绑定、全部part参数读回、几何／物理／UV／任务初态及所有受保护字段快照保持检查通过；完整材质描述精确恢复，三个固定视角恢复原版后的RGB逐值相同，最大差值为0。

[整体对照](../../../furniture_assembly/previews/author_check_20261116/LayFlatPanel/comparison_task.png)、[导向架特写](../../../furniture_assembly/previews/author_check_20261116/LayFlatPanel/comparison_panel_rack.png)、[结构化证据](../../../furniture_assembly/previews/author_check_20261116/LayFlatPanel/evidence.json)、[源码／参数／相机与版本身份](../../../furniture_assembly/previews/author_check_20261116/LayFlatPanel/manifest.json)已归档。图片由真实任务SAPIEN画面CPU读回；完整基线快照只留本地ignored输出。上述结果仅限单环境初态作者检查，不能替代物理步进、完整机器人任务、并行局部reset或A4／A5验收。

## 当前交接

素材、实际绑定、真实任务对照与有限不变项作者检查已完成；外观清晰度、原版恢复与整组取舍已由用户确认，并授权提交。 本对象没有独立新增验证框架，正式接入及 A4／A5 由 Dennis 统一组织。

## 原始来源

- [tasks/furniture_assembly/furniture_assembly_lay_flat_panel.py](../../../../../tasks/furniture_assembly/furniture_assembly_lay_flat_panel.py)

原始模型／贴图／第三方字体不复制进本档案。获取方式见[环境与资产说明](../../../../../docs/variation/SETUP.md)，原许可见[资源说明](../../../../../tasks/assets/README.md)。不同家族的apple／plate等未确认共享，分别保留目录。[总索引](../../../README.md)。

最终整组人工确认与提交授权见[人工检查记录](../../../furniture_assembly/previews/author_check_20261116/human_review.json)。原始evidence中的人工待检字段保留为运行时状态，最终反馈单独记录；正式任务接入与A4／A5状态不变。
