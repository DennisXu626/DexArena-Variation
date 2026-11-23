# Drawer & Plug 位置 variation

[作业 135501 实测报告](runtime_001/RESULTS.md) · [逐点及遥操作参数](runtime_001/POINTS.csv) · [可复制调用](runtime_001/RUN_AND_REPLAY.md)

三个短任务 62/62 个合法位置初始化通过，五个越界对照被拒。构造放置判据测试在中途单独停止，详情见实测报告。图中仍使用批准的候选范围。

[① 抽屉柜 XY](01_drawer_xy.png) · [② 抽屉柜转角](02_drawer_yaw.png) · [③ 屉内 Charger](03_charger_in_drawer.png) · [④ 桌面交接](04_charger_table_handoff.png) · [⑤ 插座 XY](05_socket_xy.png) · [⑥ 插座朝向](06_socket_yaw.png)

[首轮已审静态图及边界说明](https://github.com/DennisXu626/DexArena-Variation/blob/3ca373fa950954d3cd044c0eec36ce0fa7e69ebd/docs/variation/evidence/drawer_position_boundaries/RESULTS.md) · [短检申请和保护策略](GPU_REQUEST.md)
