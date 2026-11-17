# 目标碗（cabinet_pouring.bowl）

**限定运行与视觉检查通过，待Dennis最终查收**。作业88777，运行源码`a18cd0e26708fe2f39ff12a8a84c28735571039a`；PR #10未合并，清单暂保留pending_adaptation，不提前增加已验收数量。

接收倒出颗粒的容器。原RoboCasa model_normalized_0.obj，kinematic网格，内外表面及边缘共用material_0，沿用原UV。

## 绑定、方案与资产

实际任务覆盖：PourBeads双环境，以及Long单环境工程检查。 缺失对象记不适用，未添加占位对象。

保持原单材质槽与纹理细节，Ocean为暖色浅调，Citrus为深绿；未增加独立内外材质或改变容纳空间。

[完整部件/材质/源身份映射](bindings.json)，唯一参数来源为[cabinet-appearance-v1.2 catalog](../../../../../tasks/assets/variation/cabinet_pouring/v1/catalog.json)的`schemes.<ID>.objects.bowl`。沿用统一方案选择；新对象Violet恢复原版，原瓶/盖Violet不变，不支持逐对象任意混配。

柜体/碗采用环境私有且稳定的纹理对象，reset用upload更新像素；original恢复原像素与材质参数，原生贴图不被写入。珠子仅改材质参数。未改变UV、几何、物理或成功条件。

原模型/原纹理不复制到档案；派生贴图的原资源许可继续适用。 [制作脚本](../../../../../tools/variation/make_cabinet_tints.py)、[派生纹理与来源](../../../../../tasks/assets/variation/cabinet_pouring/v1/object_tints/provenance.json)；[原资产许可](../../../../../tasks/assets/README.md)及[获取说明](../../../../../docs/variation/SETUP.md)。旧HF revision `b197a198fe50f41d70f563cfa7c88d3cc9f528b6`仅为静态调查来源，本次运行身份以实测manifest为准。

## 验证与交付

原版与两候选同条件真实图、随机复现/记录、物理/初态保持、恢复原版、适用的双环境局部reset隔离均通过。柜体把手保持原版；独立珠子诊断与正式任务图分别标明。Long仅单环境工程检查；没有完整机器人成功、训练、A6、其它手型或长期压力结论。

[本轮真实图与全部证据](../../../../../docs/variation/evidence/cabinet_remaining/leader_fix_005/README.md)、[统一接口说明](../../../../../docs/variation/CABINET_REMAINING.md)、[固定示例](../../../../../examples/variation/cabinet_pouring/appearance.json)、[总索引](../../../README.md)。

历史：[88174视觉交验受阻](../../../../../docs/variation/evidence/cabinet_remaining/README.md)、[88509旧探针停止](../../../../../docs/variation/evidence/cabinet_remaining/visual_fix_001/README.md)。不将历史失败写成本轮通过证据。
