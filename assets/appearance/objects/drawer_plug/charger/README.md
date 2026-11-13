# 充电器（程序生成）（drawer_plug.charger）

状态：**已完成限定试点**。Bob的A1–A3材质交付已接受；PickCharger与InsertPlug各2环境的A4／A5通过。完整机器人任务成功与A6未验证，不外推其它手型／规模。

## 原始资料与加载边界

原始角色为可抓取物体／插头。V1对象键`drawer_plug/charger`，V2对应键`charger`；调查代码基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8。原始外观为程序构造机身与插脚RenderMaterial，visual／collision由任务生成；这是随代码的程序模型，不是HF模型revision。

正式任务为DrawerPlugPickCharger-Sharpa-v1与DrawerPlugInsertPlug-Sharpa-v1。原来源：[任务源码](../../../../../tasks/drawer_plug/drawer_plug_long.py)、[环境与资产说明](../../../../../docs/variation/SETUP.md)、[资源及许可说明](../../../../../tasks/assets/README.md)。原始模型／贴图／第三方字体不复制进档案。

## 唯一参数源与实际接入

- [唯一运行catalog](../../../../../tasks/assets/variation/drawer_plug/v1/catalog.json)：charger-a3-v1，original／ivory_matte／navy_satin／copper_metal。档案只引用，不复制独立catalog或材质参数源。
- [Bob部件说明与历史预览](../../../../../docs/variation/CHARGER_APPEARANCE.md)、[原预览脚本](../../../../../tools/variation/render_charger_preview.py)、[PR #2](https://github.com/DennisXu626/DexArena-Variation/pull/2)。Bob负责A1–A3，不要求其补做A4／A5。
- [正式配置及验收边界](../../../../../docs/variation/CHARGER_A4_A5.md)、[短检脚本](../../../../../tools/variation/check_charger_a4_a5.py)、[固定／随机示例](../../../../../examples/variation/drawer_plug/)。

Charger是一块本体＋两根插脚，无外部OBJ、UV或新纹理。三处box visual按charger_half／charger_prong_half分组：本体用scheme.body，插脚用catalog.prongs。原生尺寸、位置、碰撞和物理参数不变；启用时每环境材质独立。省略或关闭charger_appearance仍用原生original。

## 已验收证据

A4：两任务各2env，四固定方案、指定集合随机复现、实际ID／catalog版本、原初态与几何／碰撞／接触材质／质量／惯量对照通过。[结构化结果](../../../../../docs/variation/evidence/charger_a4_a5/results.json)。

A5：只reset env1并由navy_satin切copper_metal，env0材料／记录／完整状态与三路RGB／human像素保持不变。[本轮任务画面](../../../../../docs/variation/evidence/charger_a4_a5/README.md)。比较期间无物理步进、相机固定。

实际生产测试提交38b8474，ManiSkill3.0.0b22／SAPIEN3.0.3／Torch2.6.0；历史A4／A5单卡分配29秒。仓库整合仅CPU检查，不重跑GPU。没有真实机器人完整成功、长期压力或A6结论。

[总索引](../../../README.md)与[对象清单](../../../objects.csv)、[运行映射](../../../runtime_mapping.json)同步记录本对象状态；瓶身／瓶盖和其它对象状态保持。
