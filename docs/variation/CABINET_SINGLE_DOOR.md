# 单门柜 A/B · 使用与拍图复测

[对象档案与两件实物参考](../../assets/appearance/objects/cabinet_pouring/cabinet/README.md) · [运行目录](../../tasks/assets/variation/cabinet_pouring/cabinet_v1/catalog.json) · [CPU／后续运行检查器](../../tools/variation/check_cabinet_single_door.py)

柜体专用 `cabinet_appearance` 不依赖旧 `variation`。默认略去或设 `enabled=False` 时保持原来路径；以下只配置柜子，瓶子仍为原版：

```python
env = gym.make("CabinetPouringPickBottle-Sharpa-v1", num_envs=2,
    cabinet_appearance={"enabled": True, "scheme_id": "oak_warm_white"})
# 仅 env1 切到 B；回到 "original" 恢复原材质。
env.reset(options={"env_idx": torch.tensor([1], device=env.unwrapped.device),
                   "cabinet_appearance": {"scheme_id": "sage_walnut"}})
```

方案 ID 为 `original`、`oak_warm_white`（A）、`sage_walnut`（B）。也可配置 `per_env`（字符串 env 索引）。构建配置可与旧 `variation` 独立使用；不想改瓶子时不要传入瓶子 variation。OpenCabinet 与 PickBottle 支持，Long 及其他阶段不在这条专项路径。没有改变碰撞、质量、门角、bottle reset、机器人、成功或奖励。

## 取景与实测记录

- 关门：OpenCabinet 两环境，使用原生闭合 0°，固定前侧稍高人类相机，整柜、顶面实际角板、门面、边框和把手均在画幅。拍摄保持原生机械手；如果固定机位遮挡把手，明确标出遮挡。
- 开门：PickBottle 两环境，使用原生 90° 开门初态，不执行动作。偏高前侧视角，固定原版瓶，取门内侧、柜口、内壁、层板；同一原帧固定裁切坐标。两组使用 env0/seed 7/1280×960，原生光照与曝光，固定各组初态与构图，原版／A／B 左至右，保留六张 PNG。
- 本地按 URDF/OBJ 的实坐标投影检查顶板、柜体、把手和层板的画幅边界；这不证明机器人遮挡或实景色感。画面只能显示原模型的顶面构造，不能要求无不存在的整块顶板。
- 每任务两个独立 env 构建（原生、开启柜体），一轮内复用初始化：原生对照、采三帧、原版恢复、局部 A/B 两次。用相同外层 Torch RNG 和 seed 对比状态；记录门角，检查逐槽参数/像素、原版恢复 RGB、env0 状态/材质/RGB 不变及选中环境 RGB 改变，检查柜外所有已加载可渲染材质快照和原瓶状态。无机器人动作、训练、A6 或 Long。
- 入口：`python -B tools/variation/check_cabinet_single_door.py --approval <批准记录> --output <本线私有输出>`。脚本要求授权范围 `cabinet_single_door_rgb`、确切 Git head 和单卡 Slurm 分配。静态入口用 `--static-asset <只读柜体目录>`。无 GPU 运行时不能宣称 SAPIEN 槽或实际 RGB 验收。

## 独立拍图预算申请（尚未授权）

- 总墙钟 **60 分钟**，最多 **一次单卡作业、240 分配秒**，应用上限 **205 秒**，排队上限 120 秒，不重试、不重排。第 39 分钟为最晚提交点、剩余至少 21 分钟；第 45 分钟开始至少 15 分钟收尾。失败保留已取帧、首个错误和调度终态，不能补提。
- 提议 Ceph 专用根 `/mnt/ceph2/xkl/DexArena/cabinet_door_finish_20261120/`（本轮只读核对，并未创建）；复用 `/mnt/ceph2/DexArena/assets/task_object_meshes/cabinet_pour` 只读资产。读到 39 个柜体碰撞引用齐全，包括 8 片现有把手分解。瓶件派生文件如原任务要求生成，必须核对并隔离到本线私有目录。共享环境和资产不写入。
- 本机产物 `D:/DexArena/deliverables/cabinet_single_door_appearance/runtime_001/`，增长日志及临时传输 `D:/Logs/DexArena/cabinet_single_door_appearance/runtime_001/`。不写 C 盘。估计六张原图与两张拼图共 10–20 MiB，JSON/回传 <8 MiB，源码约 90 MiB，缓存与临时文件预计 32–128 MiB，整根正常预计低于 256 MiB；均为预算估计。
- 计划复用已验证的进程组与外层终止保护；整根 **512 MiB 每秒采样停止（可能越限，非硬顶）**，应用日志 8 MiB、单文件 64 MiB、禁 core，底层最低余量 20 GiB，本机 D 最低 10 GiB。提前刷新真实路径/余量/资产哈希/队列和 Monica；只读挂载、缓存边界、安全退出任一预检不通过就不提交。出现新的固定写盘路径或其他磁盘风险就停。
- 请求 Dennis 同时批准本次 60 分钟、一次／240 秒预算，以及上述新根和采样可能越限的风险边界。不沿用 PR #10 或 #13 的旧作业授权。生产运行和审图结果归本分支；执行层不合并。
