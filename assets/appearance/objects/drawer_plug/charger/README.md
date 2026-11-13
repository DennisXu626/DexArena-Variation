# Charger外观与正式接入状态

Bob负责材质方案交付，本线负责PickCharger／InsertPlug的接入与验收；不要求Bob补做A4／A5。

## 资料入口

- [唯一运行catalog](../../../../../tasks/assets/variation/drawer_plug/v1/catalog.json)：charger-a3-v1，original／ivory_matte／navy_satin／copper_metal。本档案不复制独立参数表或catalog。
- [Bob部件说明与历史预览流程](../../../../../docs/variation/CHARGER_APPEARANCE.md)、[原预览脚本](../../../../../tools/variation/render_charger_preview.py)、[PR #2原预览证据](https://github.com/DennisXu626/DexArena-Variation/pull/2)。A1–A3经leader限定审阅；未把作者运行报告写成独立复跑。
- [本轮配置与验证状态](../../../../../docs/variation/CHARGER_A4_A5.md)、[短检脚本](../../../../../tools/variation/check_charger_a4_a5.py)、[固定／随机配置](../../../../../examples/variation/drawer_plug/)。

## 实际绑定

Charger是任务程序生成的一块本体＋两根插脚，无外部OBJ、UV或新贴图。原任务Charger句柄下三处box visual按charger_half／charger_prong_half分组；本体用所选scheme.body，插脚用catalog.prongs。原生visual／collision构建尺寸、位置与物理参数不变；启用时每环境材质独立。

## 当前状态

- A1–A3：Bob既有交付，leader按其范围接受。
- A4：本线正式接口已在PickCharger／InsertPlug各2env通过四固定方案、随机复现、实际记录及物理／初态对照；[运行摘要](../../../../../docs/variation/evidence/charger_a4_a5/results.json)。
- A5：两任务仅reset env1并换第三方案通过；env0完整状态、材料、记录及三路RGB／human像素不变。[本轮任务画面](../../../../../docs/variation/evidence/charger_a4_a5/README.md)。

本轮新增的是既有四方案在正式任务中的运行证据，没有新增外观设计、贴图、UV或几何，也没有训练。源码测试提交38b8474，实际环境ManiSkill3.0.0b22／SAPIEN3.0.3／Torch2.6.0，单卡分配29秒。此路径与PR #3档案衔接，结论限两任务2env；不是完整任务、其它手型或A6完成。
