# PR #24 UnscrewCap 剩余补测 · 128943

实测提交 `0ed5ce09da945eeb0609f7a32fcb082cf50185cb`。首个补充机位的原版标记通过同帧实体分割，获得 204 个内缩像素，原门槛为 24。原版与十款均为同机位、seed 7、960×720。十款的真实标签、标记和材质均通过，逐款恢复原版 RGB 和材质。两次局部 reset 中未选环境的状态、材质、随机流、记录及任务和补充相机 RGB 均保持。选中环境分别保留 165、131 个原版盖标记像素。

[十款盖标记与原版](UnscrewCap_cap_marker_comparison.jpg) · [瓶签、盖和标记](UnscrewCap_bottle_cap_comparison.jpg) · [原帧／掩膜索引及 SHA256](frame_index.json) · [结构化断言和失败栈](checks.json)

## 工程阶段首个失败

`variant_9` 附着盖工程帧成功保存。切至自由盖后，检查器直接调用 `scene.update_render(...)`，报 `Modifying a scene (add/remove object/camera) is not allowed after creating the batched render system.`。生产切换修改可见性并标记渲染组待刷新，检查器直调用未经过生产渲染入口的刷新步骤。没有自由盖原帧，开口阶段、阶段隔离和 UnscrewCap 随机复现均未到达。正式 PourBeads 与独立瓶外液滴未运行。 [失败前附着盖工程帧](UnscrewCap_attached_before_failure.jpg)

沿用 [128933 的 PickBottle 瓶签、恢复和双向隔离](../runtime_003/README.md) 与 [128861 的开闭柜实景及工程结果](../runtime_001/README.md)。生产文件保持。工程触发阶段独立记账，完整机器人任务、Long、训练及 A6 不在范围。

单卡物理 3，38 GPU 分配秒，应用 35.804 秒，`FAILED 1:0`。无重排、无重试。队列、责任 PGID、可见作业 cgroup 和观察进程均已清空。Ceph 整根采样峰值 484,666,125 B，未达到 768 MiB 采样线。账务服务不可用，按终态 `scontrol RunTime` 记账。作业后 24 个冻结文件哈希一致。 [作业及清理收据](receipt.json) · [文件哈希核对](post_run_hashes.json)
