# 自由盖首帧 A/B 补测申请

CPU 调用了修改后的 capture_formal()。恰有两台目标相机、乱序并额外返回 wrist_camera 时，RGB、完整分割和参数均按目标名称取回。分别缺少基座或腕部相机时报告具体名称。四例各调用一次 get_obs()。检查器 SHA256 为 db1fb8d2588bd3afb590aaffb362c05c8726b71cfe72ef034232efefc417441d。[四例收据](CPU_CHECK.json)

申请一次单卡作业，最多 180 GPU 分配秒，应用 150 秒，外层 165 秒加 8 秒退出宽限。总墙钟 45 分钟，排队最多 120 秒，第 25 分钟前提交，至少留 15 分钟收尾。129061 已使用上次授权，本轮 GPU 0 秒。

拟用 /mnt/ceph2/xkl/DexArena/cabinet_ten_20261122/runtime_009/，现占 0 B。Ceph 整根实测 705,316,910 B，距 680 MiB 门槛 7.36 MiB，挂载余量 245.37 GiB。沿用 runtime_008 已验证的空 source/ 外层工作目录布局，在新根核对后由 bwrap 进入只读 runtime_006/source。只部署增量，预计准备少于 1 MiB，运行新增 8–24 MiB。本机日志与回传为 D:/Logs/DexArena/cabinet_ten_variants/runtime_009/，D 盘余量 117.57 GiB。交付为 D:/DexArena/deliverables/cabinet_ten_variants/runtime_009/。

提交前复核整根低于 680 MiB、Ceph 至少 20 GiB、D 盘至少 10 GiB。整根 768 MiB 约每秒采样停止，瞬时越限幅度未知。日志 8 MiB、单文件 64 MiB、禁 core，输出／缓存／临时目录分别在 256／128／96 MiB 采样停止。身份不符、启动或采集失败、切盖未生效、容量或截止时间触线即保存现场并停止。无重排、无重试。

关闭全部外观与固定 variant_9 各建双环境，seed 7，仅 env0 由生产 evaluate() 切盖。每组附着末帧、自由首帧均先保存两台默认正式相机的同次 RGB 与完整分割，再采补充机位；期间无物理步进。记录相机参数、实体位姿及 env1 对照。A 复现仍完成 B。附着帧缺目标按机位标记不可判定。尚未提交，待 Dennis 确认。
