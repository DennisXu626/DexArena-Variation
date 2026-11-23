# PR #24 阶段收尾 · 作业 128997

实测提交 `8fc1db86be19520d9212d7b4b06203cb75a6f39c`。`variant_9` 附着盖工程帧通过，原帧与 `128943` 同机位附着帧哈希一致，实际 `source_fixed`／`cap_fixed`、瓶签材质和 204 个盖标记像素已核对。生产渲染组刷新后成功取得自由盖首帧，前一次的批量渲染异常未复现。

自由盖首帧的相机内外参数比对通过，但原瓶签位置被大块前景覆盖。`source_fixed` 的实体像素为 0，标签投影为 2,669，投影与实体掩膜无交集，检查器按原门槛停止。`cap_twin` 的分割与隔离核对未到达，无法区分遮挡、渲染缓冲姿态更新或实体对应关系。开口瓶、UnscrewCap 随机复现、正式 PourBeads 和独立瓶外液滴未运行。

[附着与自由首帧全景](UnscrewCap_stage_full_frame_comparison.jpg) · [同坐标工程近景](UnscrewCap_stage_comparison.jpg) · [原帧和掩膜索引](frame_index.json) · [首个失败栈和结构化结果](checks.json) · [全帧比对](frame_comparison.json)

继续引用 [128861 柜体开闭图](../runtime_001/README.md)、[128933 PickBottle 瓶签](../runtime_003/README.md) 与 [128943 UnscrewCap 十款附着盖、恢复和双向局部隔离](../runtime_004/README.md)。本轮仅工程触发，没有实测机器人动作或长任务。

作业 `FAILED 1:0`，单卡分配 17 秒，应用 14.969 秒。一次提交，无重排、无重试。责任进程组、可见作业 cgroup 和队列清空，观察进程已退出。Ceph 整根采样峰值 585,936,139 B，低于 768 MiB 采样停止门槛。`sacct` 不可用，时间取终态 `scontrol RunTime`。作业后 26 个冻结文件哈希一致。 [终态及清理收据](receipt.json) · [后置哈希核对](post_run_hashes.json)
