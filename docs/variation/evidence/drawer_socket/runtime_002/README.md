# Drawer & Plug 短检复测 · 作业 121640

**抽屉和插座两组任务实景已采齐，工程检查通过，待 Dennis 审图。**

| 任务 | 环境 | 结果 |
|---|---:|---|
| OpenDrawer | 2 | 两次原生独立构建的五阶段 RNG 摘要、初态、物理、材质和全部 RGB 一致；显式关闭、original、两个候选及其恢复、随机复现、局部 reset 隔离通过。 |
| PickCharger | 2 | 抽屉的原生／关闭／original、两个候选、初态与物理、恢复、复现和局部隔离通过。Charger 兼容性单独通过。 |
| InsertPlug | 2 | 插座的原生／关闭／original、两个候选、初态与物理、恢复、复现和局部隔离通过。Charger 兼容性单独通过。 |
| Long | 1 | 抽屉、插座的原生对照、候选、恢复、复现，Charger 兼容及 `charger_pick_place`、`charger_insert` 工程阶段 reset 通过。双环境隔离不适用。 |

三短任务分别两次只 reset env1，无物理步进：env0 状态、材质及贴图、记录、外观随机流、全部相机 RGB 不变；env1 目标物体由分割标识独立核对，同一 post-reset 状态下两次均有目标像素变化。Charger 联动另做，切换 Charger 时新物体的材质保持；InsertPlug 三列展示用原生 Charger，变化来自插座本身。Long 两套候选均有 drawer 和 socket 各自的目标像素变化。

[抽屉三列图](drawer_comparison.png) · [插座三列图](socket_comparison.png)

- **抽屉。** 原版右侧大板的纵向木纹明显；暖白和浅灰在同一位置均未见残留木纹。暖白更亮、略偏暖，浅灰更沉。三层接缝及浅银色把手保留；关闭姿态看不到内侧，画面上沿略裁到柜顶。不能仅凭这组静态光线鉴别涂装／层压板工艺。
- **插座。** 原版正面呈均匀银灰；暖白和炭黑候选的边缘、顶面与侧面分界更清楚，未见显眼的尖锐高光，呈平滑哑光。原版在此光照下也没有很强的镜面亮斑，不能据图量化光泽。炭黑壳体上仍可辨认两条孔缝，但对比低，靠手的一孔边缘被指尖部分挡住；看不清孔内深度。整体图里的 Charger 维持原版。
- 两组都使用任务 `render_camera`，env0、seed 7、相同的原生初态、任务灯光和曝光设置，原帧 1280×720。各列只作统一缩放与同坐标裁切，不调色或调亮。[抽屉坐标与哈希](drawer_capture.json) · [插座坐标与哈希](socket_capture.json)。

**复测版本。** 交验起点 `108e5c41aa384319ecb0e86124d8322aa4dc7baa`，实际运行 `f51424c5d5fc8c398260b3f2ccfea6bcd6894e95`。只变更短检脚本：每条比较序列在构建前一次性恢复同一份 Torch CPU 和当前 GPU RNG，下列各阶段留证：构建前、构建后、显式 reset 后、两次无 seed 局部 reset 后。无中途回拨。两次原生 OpenDrawer 对照通过，第一个实例即后续基线。33 次构建包括原 32 矩阵和新增的一次必要原生对照。任务生产树、方案和参数逐字节未改；96 个既有抽屉资产经只读 CPU 预检匹配。

**作业与限制。** 121640，`lyg0295` 物理卡 3，`COMPLETED 0:0`，单卡分配 110 秒（Slurm `scontrol`；`sacct` 后端不可用）；应用约 108.7 秒。9 分钟调度、应用上限 500 秒，未重排、未重试，责任进程组、可见作业 cgroup 和本线队列已空。Ceph 整根含历史留存的采样峰值 318,992,650 字节（约 304.2 MiB）；768 MiB 为采样停止阈值。保留 Vulkan ICD 和 PhysX 凸包警告，未阻断本次构建、断言或取图。未测试完整机器人任务、训练、A6 或 Long 双环境。保持草稿，待 Dennis 审图，不合并。

[结构化结果](results.json) · [五阶段 RNG 对照](RNG_AUDIT.json) · [目标物体像素计数](TARGET_PIXELS.json) · [运行文件和版本](manifest.json) · [哈希审计](HASH_AUDIT.json) · [作业收据](JOB_RECEIPT.json)。

六张全分辨率原始 PNG 随本地交付保留；两个 capture.json 记录原帧名、坐标和 SHA256。GitHub 证据保留两张 PNG 对照图。
