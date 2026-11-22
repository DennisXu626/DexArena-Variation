# InsertPlug 三项补测 · 作业 128908

三个缺口均已补齐。实测提交 5aafbc02212427489ddb298da9ed844fdab8e3bd。生产文件与作业 128860 实测提交 f244804b92bb0ae43984ebce2876051c33d3f50b 一致。

| 项目 | 实际结果 |
|---|---|
| Charger 恢复 | 真实 reset env0 将 Charger 移动 **5.92 cm**。在新位姿上，真实恢复帧与原生材质参考整帧 RGB 相同。按同帧实体分割及部件投影核对，壳体 19,605 像素、两个插脚 1,266 和 1,140 像素，各自零差异。换成同位姿 variant_4 的错误对照后，壳体 19,605 像素全部有差异，双插脚保持原样。未选 env1 的状态、材质、记录、随机流和各路 RGB 均通过隔离检查。 |
| 随机复现 | 任务 seed 7，外观 seed 109。两次独立构建按整批、env1、env0、env1 的序列 reset，包含构建时记录在内，两侧七条逐环境记录完全一致。env0 选择序列为 original、6、6，env1 为 original、1、2、8。 |
| 插座双孔 | 保留原任务相机。新增固定展示机位，第一次 original 即确认双孔无遮挡。随后同 seed、同初态、同相机、同光照与曝光采原版加十套，十一格全齐。每格两个孔分别有 2,042 和 1,987 个无遮挡的投影内点。最深壳面与孔的最小中位亮度差为 31 个 RGB 码值，逐格打开检查可清楚辨认两个矩形孔。 |

本轮只运行 InsertPlug。OpenDrawer、PickCharger、InsertPlug 原有十一格、逐款恢复、同 seed 初态及 env1 reset 继续引用作业 128860。没有开展机器人任务成功、训练或 Long 验收。

作业 128908 在 lyg0295 物理卡 3 正常结束，GPU 分配 30/180 秒，应用 29.06/150 秒，排队 0 秒。一次提交、无重排与遗留责任进程。Ceph 整根采样峰值 319,605,449 字节，约 304.8 MiB。Slurm 账务服务不可用，分配时长采用调度器终态 RunTime。

## 实景与原帧索引

- [插座双孔十一格近景](InsertPlug_socket_close_socket_board.jpg)
- [插座补充机位全景](InsertPlug_socket_close_scene_board.jpg)
- [Charger 同位姿三列对照](Charger_same_pose_comparison.jpg)
- [原帧哈希、逐次随机记录和三个结果](checks.json) · [作业收据](job_receipt.json)
- [复用作业 128860](../runtime_001/README.md) · [补测判据](../INSERT_FOLLOWUP.md)
