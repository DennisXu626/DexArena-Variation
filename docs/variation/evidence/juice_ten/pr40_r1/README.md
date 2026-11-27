# PR40-R1 独立验收证据

冻结源码 `b9b4ab662b86b6227040d429890f14a721c6a4b7`，Server 3 / lyg0295 / G6，作业 143212，退出码 0。正式 main 基线 `6e3467b`，包含 PR19 squash `d02df83`。

- [汇总](summary.json)：六入口 A4 66/66、双向 A5 120/120、独立进程四步 66/66、临界 reset 6/6、96 行新增 ID 覆盖。
- [完整覆盖矩阵](coverage_matrix.json.gz)：六入口×ID 3–10×env0/env1，含实际材质、恢复和可见性边界。
- [A4/A5 独立核查](a4a5_integrity.json)、[签名及源码核查](integrity.json)、[轨迹差值](trace_integrity.json)：708 签名块匹配，轨迹最大差 0，15 个运行源码文件与 138333 归档一致。各入口目录有完整 report、identity、signatures 压缩文件。
- [短轨迹](short_trace/trace.json.gz)、[临界 reset](critical/report.json.gz)、[图片哈希](image_hashes.json.gz)、[预览 manifest](preview/manifest.json) 保留原始结构化结果。
- [资产身份](asset-identity.json)：60 个文件与 138333 一致。[源码差异](runtime_source_deltas.json) 与 [作业后哈希](source-after-check.txt) 可核实冻结代码。
- 苹果 [#5 橙](preview/apple_in_fridge_variant_5.png)、[#6 蓝](preview/apple_in_fridge_variant_6.png) 使用可见果实的视角；底座 [#5 黄](preview/seated_lid_button_variant_5.png)、[#7 橙](preview/seated_lid_button_variant_7.png)、[#10 象牙](preview/seated_lid_button_variant_10.png)；[独立盖](preview/loose_lid_variant_5.png) 与集成盖分别核对。其余原始 PNG 保存在 Server 3 `/data/home/pb/juice-pr40-r1-20261126/results-143212`，哈希在归档中。

预览是单环境 CPU 物理＋GPU 渲染；A4/A5 是双环境 PhysX CUDA＋GPU 渲染。默认 AppleToBlender 相机的苹果像素为 0，不能作为其颜色可见证明；env1 的目标可见像素未被检查器单列。完整机器人成功率等未测试，详见[主报告](../../../JUICE_PR40_R1.md)。
