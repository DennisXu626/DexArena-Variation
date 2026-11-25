# Server3 双环境 CUDA 实测

作业 `142367` 在 `lyg0295` 的 NVIDIA A800-SXM4-40GB 上顺序执行 ClickMouse、TypeKeys、OpenLaptop。三个检查器分别返回 0，均生成独立的 SDK 回执、逐点记录和逐步动作轨迹。三项写出通过回执后，Slurm 在作业收尾记录 `TIMEOUT`，用时 36:05。[检查器状态记录](142367/status.txt)

三个任务均使用提交 `f9f64ecf71b583319f7850400c08492c9d5e4d76`、Linux SAPIEN `3.0.3+dexarena.gpu1.linux1`、PhysX `105.1-physx-5.3.1.patch0` 和 indexed GPU apply v1。每份运行报告中的 17 个源文件哈希均与该提交对应的 Git 文件一致。三个任务的场景资产哈希与 Windows CUDA 记录一致。机器人资产中有 32 个文本文件因工作区换行不同产生哈希差异，统一为 LF 后逐文件一致。SDK 回执的映射路径从安装目录 `runtime-common` 起列出，各回执保留原始文件的 SHA256。

每项的 33 行包含 17 个合法位置、12 个预期拒绝及 4 个跨环境隔离检查。三个任务均通过。合法点的操作位置最大预测误差分别为鼠标 0.00026 mm、键盘 0.00034 mm、笔记本 0.00035 mm。CSV 的每行包括种子、环境索引、复现参数及实测结果，JSON 的 `actions` 保存原生控制与接触轨迹。

| 短任务 | Server3 实际动作及与 Windows CUDA 的对照 | 作业 142367 的独立证据 |
|---|---|---|
| ClickMouse | 两个平台的标称位置两条路线均未触发有效点击。远点两条路线均达到左键满行程，其中壳侧路线触发原生成功。所有试次的指定 link 对接触力读数均为 0 N。 | [逐点 CSV](142367/ClickMouse/POINTS.csv) · [原始 JSON](142367/ClickMouse/report.json) · [SDK](142367/ClickMouse/SDK.json) |
| TypeKeys | 标称与远点均完成 P 的按压与释放，原生阶段推进至 A。两处指定指腹力峰值为 3.81 N、3.64 N，与 Windows CUDA 的读数四舍五入到 0.01 N 后一致。五键序列仍需遥操验证。 | [逐点 CSV](142367/TypeKeys/POINTS.csv) · [原始 JSON](142367/TypeKeys/report.json) · [SDK](142367/TypeKeys/SDK.json) |
| OpenLaptop | 标称与远点的主动动作屏角峰值分别为 60.61°、67.10°。两次指定指尖对屏幕的接触力均为 0 N，未完成指定接触的开盖动作。Windows CUDA 上观察到相同结果。 | [逐点 CSV](142367/OpenLaptop/POINTS.csv) · [原始 JSON](142367/OpenLaptop/report.json) · [SDK](142367/OpenLaptop/SDK.json) |
