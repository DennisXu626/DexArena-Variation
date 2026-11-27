# 新配色与灰白果皮修复后的正式回归

2026-11-24，Server 3 / lyg0295 / G6，共享一个命名 shard。作业 **138333，COMPLETED 0:0，49分07秒**。Sharpa、2env、PhysX CUDA＋GPU 渲染、seed7、noise0。Slurm 使用 --export=NONE、--gres=gpu:6，无嵌套 srun。

运行版本为 e435094 工作树加本轮新配色及灰白果皮遮罩修改，catalog 为 juice-ten-v3-preview；没有为消除 preview 字样而在测试后重命名版本。source_snapshot.tar.gz 和 source_manifest.json 固定实际运行的15个源码/配置文件，已逐文件核对快照和当前工作树 SHA-256。

|入口|A4|双向A5|独立进程四步|
|---|---|---|---|
|OpenFridge|11/11|20/20|11/11|
|AppleToBlender|11/11|20/20|11/11|
|CloseFridge|11/11|20/20|11/11|
|PlaceLid|11/11|20/20|11/11|
|PressButton|11/11|20/20|11/11|
|Long|11/11|20/20|11/11|

总计66行A4、120例双向A5、66对独立进程四步和6例临界reset均通过。708个规范JSON签名块已独立重算哈希，全部匹配；66对的物理/控制初态和完整轨迹逐值复核最大差0，见 integrity.json。临界夹具覆盖 PressButton/Long 末步前计数、Long阶段、AppleToBlender路线锁存与运动缓存的双向隔离。

实际资产60文件身份见 asset-sha256.txt。各入口包含 report、identity、完整 signatures 的 gzip 与全部原帧哈希。short_trace_trace.json.gz 是本次全部66对初态、控制器、drive与轨迹；critical_report.json.gz 是本轮六例临界状态，不用旧运行结果代替。slurm.out.gz 和 receipt.txt 保存完整日志及收据。

## 图片

本地可上传图片集中在 outputs/juice_v3_regression/gallery：六入口A4人类相机图册、Long双向A5四联图、最新苹果及完整底座近景。

A4/A5原图在服务器 /data/home/pb/juice-ten-20261124/v3-regression-138333，各图片SHA随入口归档。图册为原帧缩略拼接，不替代原帧。默认相机存在机器人遮挡，尤其AppleToBlender/Long的果皮；目标不可见不写成视觉通过，苹果外观审核使用单独近景。

最新苹果近景来自138329（v3灰白果皮修复），完整底座来自138281（v2，新底座配方与v3相同），两者为CPU物理＋GPU渲染真实任务预览。它们不冒称本次双环境CUDA检查帧。此前六组旧近景含已替换的苹果/底座配色，不作为本版完整近景交付。

## 变更与边界

保留original和1/2号旧配方与旧算法输出；3～10号苹果改为紫、青蓝、橙、蓝、白、玫红、黑、黄绿，并启用目标饱和度/亮度映射，将原贴图冷灰/灰白果皮纳入遮罩。底座5号黄、7号橙、10号象牙白，2号灰蓝保留。预览与生产复用同一改色函数。

数值阈值仍1e-6；RGB最大1、最多8通道。短步每个原生和候选分别全新Python进程，进程间严格串行，每个worker内部2env。先前同进程失败及定位实验仍保存在父证据目录，不删除或覆盖。

随机选择未实现；未测完整机器人成功轨迹、其它手型/并行规模/seed/噪声、长期压力和性能/显存。结论为此固定范围作者侧回归通过，未替代维护者审阅。本轮作为十方案分支的后续提交交付，PR由作者发起。
