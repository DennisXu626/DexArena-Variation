# Juice Preparation 外观与双环境验证交付

状态：四对象的 original＋两套新外观已制作，用户已完成人工预览审查；六任务限定双环境验证通过，待 Dennis 最终审阅。[PR #19](https://github.com/DennisXu626/DexArena-Variation/pull/19)已发起；本轮 R1 作者修正与 main 整合待用户提交，不代表正式集成验收通过。

分支 `codex/juice-preparation-appearance`，来自团队本地固定基线 `acd6ba232b8da7a97fd313aa3df8a9f595fd55e0`；现已整合 main 的 aee41a3439287a17ce9d4c14c6320fa6f5b4579d，并保留其它家族已合入内容；本地合并和 R1 修正尚未提交。

## 部件、方案与素材

唯一参数源：[catalog](../../tasks/assets/variation/juice_preparation/v1/catalog.json)，版本 juice-preview-v1。无新模型、UV、第三方素材或离线贴图文件；纹理在内存中由原贴图改色。原资源沿已有授权渠道获取，实际运行的 60 个文件哈希见 [manifest](evidence/juice_preparation/manifest.json)，历史 HF revision 不代替本次身份。

| 对象 | 实际视觉绑定 | variant_1 | variant_2 | 保留 |
|---|---|---|---|---|
| 迷你冰箱 | tabletop_mini_fridge_v1 中 body_visual.glb、door_visual.glb 的原浅色外壳槽 | 鼠尾草绿 #769184，粗糙度 .38 | 陶土色 #A95647，粗糙度 .58 | 门缝、把手、内部其它槽 |
| 苹果 | robocasa_apple_0/visual/model_normalized_0.obj 原漫反射贴图 | 金黄 #D9AD42 | 青绿 #93A752 | 原 UV、明暗和果梗细节 |
| 搅拌机 | Blender023 的 Body001.obj 表面纹理 | 深绿 #285C53 | 灰蓝 #344B60 | 透明杯体、按钮及其它槽 |
| 搅拌机盖 | lid.obj；独立盖及集成盖共用 lid 角色 | 浅绿灰 #A9BDB2 | 浅米灰 #C1B5A7 | 轮廓、开口和图案结构 |

苹果使用原贴图 HSV 加权改色，搅拌机与盖使用保留亮度的着色。冰箱仅改颜色／粗糙度。每环境独立可变材质和纹理；冰箱 GLB 临时私有副本用于隔离渲染缓存，文件字节不变。金属度等其它通道、物理与碰撞不随方案修改。

## 接入入口与使用

覆盖 `JuicePreparation{OpenFridge,AppleToBlender,CloseFridge,PlaceLid,PressButton,Long}-Sharpa-v1`。苹果在 AppleToBlender／Long，独立盖在 PlaceLid／Long，集成盖在 PressButton。开关默认关闭；省略 `juice_appearance` 不创建绑定，空字典则启用 original。

```python
env = gym.make(
    "JuicePreparationLong-Sharpa-v1",
    num_envs=2, sim_backend="physx_cuda", obs_mode="state",
    render_mode="rgb_array", reconfiguration_freq=0,
    robot_init_qpos_noise=0,
    juice_appearance={"per_env": {
        "0": {"scheme_id": "variant_1"},
        "1": {"scheme_id": "variant_2"},
    }},
)
env.reset(seed=7)
env.reset(options={
    "env_idx": torch.tensor([1], device=env.unwrapped.device),
    "juice_appearance": {"scheme_id": "original"},
})
records = env.unwrapped.juice_appearance.records
```

仅选中环境在 reset 时应用方案。记录 env_idx、scheme_id、catalog_version、episode_index；构造器也会 reset，计数不等于用户显式 reset 次数。当前成套固定选择，未实现集合随机和任意对象混搭。

## 历史 GPU 运行（R1 修正前）

最终作业 **123675**（Long，48 秒）、**123676**（五个子任务，122 秒），Server 3 / lyg0295 / G7，均 COMPLETED、ExitCode 0:0。详见 [结构化证据](evidence/juice_preparation/README.md)。

- env0 / env1 分别使用 variant_1 / variant_2，核对实际材质和画面确已改变，非仅检查方案名称。
- 只 reset env1 到 original；env0 的物理／任务状态、材质、画面、RNG 和回合记录保持。
- 恢复后的 env1 与独立关闭外观基线逐槽比较，六任务共 73 槽的参数和全部已检查纹理通道一致；env0 与恢复原版 RGB 最大差、变化通道数均为 0。
- 质量、惯量、质心、碰撞形状／网格／局部姿态／接触材质、关节限位／摩擦／驱动签名一致。
- 同 seed 初态及 16 步零动作的状态和 tensor 型 info 输出一致，状态最大差为 0。比较对象是同一适配代码关闭／开启外观，不能称为未改动旧版本的双环境对照。

原代码存在单环境限制和批量初始化假设。本次仅在本家族内补齐逐环境布局、目标几何、按钮校准和局部初始化索引；任务门槛及阶段顺序保持。未修改共享机器人、仿真配置或其它家族。

## 加载与运行成本

下表为关闭 / 开启外观；构造为单次计时，步进为后 15 步中位数，渲染为 3 次中位数。

| 任务 | 原版槽数 | 构造秒 | 步进毫秒 | 渲染毫秒 |
|---|---:|---:|---:|---:|
| Long | 19 | 2.807 / 4.312 | 848.58 / 820.07 | 4.18 / 4.19 |
| AppleToBlender | 18 | 1.955 / 3.926 | 552.14 / 550.99 | 4.07 / 4.05 |
| CloseFridge | 11 | 1.396 / 1.433 | 270.86 / 271.09 | 4.06 / 4.04 |
| OpenFridge | 11 | 2.060 / 1.428 | 353.27 / 346.04 | 4.02 / 4.02 |
| PlaceLid | 7 | 1.666 / 2.057 | 554.15 / 553.70 | 2.35 / 2.36 |
| PressButton | 7 | 1.587 / 2.038 | 555.40 / 556.28 | 2.43 / 2.40 |

贴图任务增加约 .4–2.0 秒构造时间。本次串行单次测量受缓存与共享 GPU 影响，不承诺吞吐比例或规模上限。JSON 中 Torch 分配器峰值和进程 RSS 是高水位，不能当作 SAPIEN 总显存或显存增量。最终两作业为 170 shard-wall-seconds，非独占 GPU 计算秒；早期排障成本不在该合计中。

## 复现与图片

[预览脚本](../../tools/variation/render_juice_preview.py)保持同初态、相机、光照，在真实任务场景比较三方案；apple_in_pitcher 是明确标注的受控放置，其余为任务原生 reset 状态。预览作业 91316／91317 是单环境 CPU 物理＋GPU 渲染，不能替代本次双环境 CUDA 物理证据。

获授权后在 Slurm GPU 作业内、仓库根目录执行，先准备原任务需要的可写资产副本：

```bash
export PYTHONPATH="$PWD"
python -B tools/variation/render_juice_preview.py --catalog tasks/assets/variation/juice_preparation/v1/catalog.json --output outputs/variation/juice_preview

mkdir -p outputs/variation/juice_verify/tmp
export TMPDIR="$PWD/outputs/variation/juice_verify/tmp"
python -B tools/variation/check_juice_parallel.py Long
```

替换 Long 为其它子任务后缀。提交仍遵循 pair-slurm 的指定 GPU Index、`--export=NONE` 和禁止嵌套 srun 规则。实际运行包装脚本另见证据目录，不在 SSH 提交层直接运行 GPU 工作。

PR 建议附已审查的六组 original／两候选近景对照，以及 Long 的 env0-before／env0-after、env1-before／env1-restored 四张隔离图。隔离图用任务默认相机，有机器人遮挡，仅用于隔离复核；审美沿用近景图。PNG 保留于输出目录，手动附 PR，不提交整批大型输出。

## 未测与交接

已测限 Sharpa、2env、seed 7、机器人初态噪声 0、固定方案、原生初态附近局部 reset 和 16 步零动作。未测其它手型／规模／seed、非零噪声、随机方案、长时间压力或完整机器人成功轨迹；未对已处于成功临界阶段的环境做局部 reset，不外推所有阶段计数器的隔离。原任务判定的完整成功轨迹仍待负责人验收。

早期排障作业不作最终通过依据；部分短时 scontrol 记录已过期，明确列为无法从当前控制器追溯。最终收据已导出。私有运行副本、临时资产及图像暂保留审查；未删除共享资源，也未批准或合并 PR。

## PR19-R1 作者修正

错误请求预校验、局部 reset 临界状态保护、main 冲突解决和按 ID 标图已完成作者侧修正，CPU 回归通过；新版本 GPU 复验待 head 冻结后安排。完整命令、证据边界与版本见[R1 修正报告](JUICE_PR19_R1.md)。

## 十套扩展（作者工作分支）

保留本页 PR19 两套历史说明。新增八套见 [十套方案](JUICE_TEN_VARIANTS.md) 和 [本轮证据](evidence/juice_ten/README.md)，作为独立十方案分支交付，PR 由作者发起。
