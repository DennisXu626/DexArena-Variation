# 自由盖 A/B 启动验证及预算申请

正式运行根 /mnt/ceph2/xkl/DexArena/cabinet_ten_20261122/runtime_008 的空 source/ 已核对。正式 run_owned 和 bwrap 拉起一次 CPU 探针，工作目录为 runtime_006/source，生产模块从该树解析。检查器 SHA256 为 6e6d7003f64daad724f7f3d8178e345a59bb25cd9f03348ed56f2f332a46b85d。子进程正常退出 0，日志 368 B，PGID 1254128 清理完成。CPU 收据单独归档，正式提交与运行标记均未占用。GPU 使用 0 秒。详见 [启动收据](CPU_RECEIPT.json)。

申请一次单卡 180 分配秒，应用 150 秒，外层 165 秒加 8 秒退出宽限，总墙钟 45 分钟，至少留 15 分钟收尾。排队最多 120 秒，第 25 分钟前提交，禁重排和重试。129060 的授权已经使用。

整根现占 705,013,395 B，距离 680 MiB 提交门槛 7.65 MiB。runtime_008 占 493,626 B；Ceph 可用 245.44 GiB。本机 D:/Logs/DexArena/cabinet_ten_variants/runtime_008/ 的传输包 4,973 B，D 盘可用 117.69 GiB。本地交付 D:/DexArena/deliverables/cabinet_ten_variants/runtime_008/。提交准备预计再增不足 1 MiB，运行预计新增 8–24 MiB。提交前重测整根低于 680 MiB、Ceph 至少 20 GiB、D 盘至少 10 GiB。运行时整根 768 MiB 约每秒采样停止，最大瞬时越限量未知。应用日志 8 MiB，单文件 64 MiB，禁 core。输出、缓存、临时目录分别按 256、128、96 MiB 采样停止。

两组各双环境，seed 7，先附着末帧，再由生产 evaluate() 仅对 env0 切盖。先取两台默认正式相机，再取补充机位。异常复现时完成另一组；若切盖未生效、采集失败、身份或容量保护触线则留证停止。审批后才提交。目前两组均待采集。
