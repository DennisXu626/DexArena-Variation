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
- A4：本线已补最小正式接口及静态准备，实际运行未测，待本轮新GPU预算。
- A5：两环境局部reset脚本已准备，实际状态／材质／RGB隔离未测。

本轮没有新的图片、贴图、UV或几何，也没有训练。此路径与PR #3对象档案衔接；不得将“有目录／有代码”写成正式任务验收完成。
