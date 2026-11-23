# PR #24 分项收尾 · 129056

实测提交 `952af8c36ab1ae8392c7e6b8cfc28b19b4a212f9`。三个独立检查通过，最后的自由盖诊断未通过。草稿交 Dennis 审验。

| 分项 | 结论及证据 |
| --- | --- |
| UnscrewCap 随机复现 | 两次独立构建的 7 条逐环境回合记录逐项相同。 [原始记录](unscrew-random.json) |
| 正式 PourBeads | 原版及十款碗面、口沿的同机位 RGB 对照，瓶、碗和 16 颗粒的实绑定、物理／初态、逐款恢复、随机复现、双向局部 reset 通过。各方案均保留原生瓶内初态，两环境各 16 颗。 [碗十一格](PourBeads_bowl_comparison.jpg) · [结构化断言](pour-task.json) |
| 独立瓶外液滴 | 16 颗原生 4 mm 球，原版及十款的 176 个逐球掩膜和 RGB 对照通过。 [独立诊断十一格](PourBeads_exposed_droplets_comparison.jpg) · [逐球断言](pour-droplets.json) |
| 自由盖 | 附着 RGB 与 128997 一致。生产 `evaluate()` 切到自由盖后首帧仍未通过。开口阶段未运行。 [双环境对照](UnscrewCap_stage_full_frame_comparison.jpg) · [断言、实体及位姿](cap-diagnostic.json) |

## 首个差异

环境 0 的生产脱离标志已置位，`source_fixed` 位姿与相机保持，自由盖已移到瓶口。固定瓶和自由盖组件报告可见，但实际实体分割均为 0 像素。原标签区域 1,487 像素中，986 为 `scene-0_bottle_placement_region`（ID 57），501 为 `mobile_base_link_6`（ID 3）。原门槛在第一条 `source_fixed` 掩膜断言停止。环境 1 前后 RGB 和全分割哈希匹配，相机、固定瓶位置和阶段标志匹配。前景辨识来自同帧完整分割，具体内部原因仍待审验。 [首个差异明细](cap_first_difference.json)

[附着／自由原帧和完整实体分割](cap_frames/) · [92 个原帧与掩膜哈希索引](frame_index.json) · [分项状态](checks.json)

历史 [128861 开闭柜](../runtime_001/README.md)、[128933 PickBottle](../runtime_003/README.md)、[128943 十款附着盖](../runtime_004/README.md) 与 [128997 附着基线](../runtime_005/README.md) 均保留。本轮自由盖仅工程触发生产切换，没有执行机器人动作。

单卡分配 96 秒，应用 93.43 秒，一次提交。没有重排或重试，队列、责任进程组和可见作业 cgroup 清空。整根采样峰值 703,983,857 B，低于 768 MiB 停止线。按终态 `scontrol RunTime` 计费。运行后 28 个冻结文件及运行入口均匹配。 [作业收据](receipt.json) · [哈希核对](post_run_hashes.json)
