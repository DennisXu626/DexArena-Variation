# PR #24 独立收尾与自由盖首帧取证

## 复用的证据

- [128861 柜体开闭](runtime_001/README.md)。后续唯一生产文件差异为瓶签绑定，柜体证据仍适用。
- [128933 PickBottle 瓶签、恢复和双向隔离](runtime_003/README.md)。生产文件及已冻结资产一致。
- [128943 UnscrewCap 附着盖十款、恢复和双向隔离](runtime_004/README.md)。生产文件及已冻结资产一致。
- [128997 附着盖基线](runtime_005/README.md)。附着原帧哈希与 `128943` 相同。自由首帧为历史失败证据。 [复用哈希清单](independent_closeout_reuse.json)

## 生产切盖与旧工程触发的差异

| 项目 | 生产 `UnscrewCap.evaluate()`／`_cap_status()` | `128997` 旧检查器 `cap_switch()` |
| --- | --- | --- |
| 脱离标志 | 位姿达标、转角达到 π、低速保持三个控制周期后先置 `_cap_detached`。`_swap_in_twin()` 再置 `_cap_free`，`evaluate()` 锁存 `_stage_cap_turned`。 | 直调 `_swap_in_twin(0)`，只置 `_cap_free`，未更新 `_cap_detached` 或阶段锁存。 |
| 可见性、碰撞与指示区 | `_set_ghost_active()` 隐藏附着盖、显示自由盖并更新碰撞组。固定瓶继续可见。更新脱离后的螺纹摩擦和盖放置指示区。 | 同样执行盖体可见性与碰撞切换。另调 `_sync_bottle_representation_runtime()` 全部图元和重力同步，未执行螺纹摩擦与指示区更新。 |
| GPU 提交 | `_cap_status()` 只提交刚体数据，再 `_gpu_fetch_all()`。指示区若改变，另按生产规则提交并读取刚体数据。 | `_flush_bottle_representation_state()` 另外提交 articulation 根位姿、根速度、qpos 和 qvel，再 `_gpu_fetch_all()`。 |
| 瓶身表示与取图 | 自由阶段用 `source_fixed`／`cap_twin`，放置确认后才切 `source_open`。生产渲染入口按需刷新批量组。 | 原检查器表示预期相同。`128997` 刷新后首帧画面异常，`source_fixed` 实体像素为 0。现有证据不足以认定原因。 |

新诊断仅在环境 0 设定转角及保持计数输入，由现有生产 `evaluate()` 走完整脱离分支。固定 `variant_9`、seed 7、原机位、两环境。每个阶段在任何像素断言前保存两个环境同一次采集的原始 RGB、完整实体分割、前 12 个前景实体名称及像素计数。另记录瓶身各表示、附着和自由盖的实体 ID、可见性及位姿，以及相机内外参、世界位姿和阶段标志。实体 ID PNG 按 RGBA 四字节由低到高无损保存，解码为小端 `uint32`。自由盖首帧通过原有标签及标记门槛、可见表示和隔离断言后，才工程触发既有开口瓶切换。三阶段都标注为诊断，不代表机器人达成任务。

## 独立入口和结果顺序

使用 `check_cabinet_ten_variants.py --followup` 分开运行以下四项，每项各有 `results.json`、`manifest.json`、可用原帧及哈希。

1. `unscrew-random` 两次独立构建，使用同 seed 和同局部 reset 次序比较逐环境选择与回合记录。
2. `pour-task` 保留正式 PourBeads 瓶内初态，原版＋十款同机位碗面、口沿证据。保留瓶／碗／16 颗粒绑定、物理与初态、恢复、随机复现及双向局部 reset 断言。
3. `pour-droplets` 单独实例，原有 16 颗半径 4 mm 的液滴移出瓶外。逐颗分割、编号掩膜和实际 RGB，对照图独立标注。
4. `cap-diagnostic` 最后独立排查自由首帧，确保不会阻断前面三项。失效时保存对照帧及首个差异，不切机位、不重复尝试。

CPU 验证通过独立分派、审批前拒绝、两环境实体 ID 大于 65,535 的无损往返、实体名称及位姿记录。尚未使用 GPU，也未更改生产。申请一次单卡 480 GPU 分配秒，应用 420 秒，总墙钟 60 分钟且至少留 15 分钟收尾。新输出拟用原 Ceph 根下 `runtime_006`。申请提交前门槛 680 MiB，运行仍按 768 MiB 采样停止。待 Dennis 批准，PR 保持草稿。
