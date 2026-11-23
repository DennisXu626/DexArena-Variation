# 十套外观 variant 怎么做环境验证

每个适用的任务入口用原版 `original` 作对照，加上十套新外观，共 **11 行**。最接近的现成例子是 Furniture Assembly，它在 LayFlatPanel、InsertRail、FastenScrew 三个短任务里逐款检查了十套候选。

| 想看什么 | 从哪里看 |
| --- | --- |
| 十款怎么逐个拍、怎么核对方案编号 | [家具验证说明](../FURNITURE_APPEARANCE.md) · [LayFlatPanel 的 11 张原图及局部 reset 对照](../../../assets/appearance/furniture_assembly/previews/runtime_finishes/LayFlatPanel/) · [三个任务的结果 JSON](../../../assets/appearance/furniture_assembly/previews/runtime_finishes/summary.json) |
| 在 Linux 服务器上，怎样证明一个环境换色后另一个没受影响 | [Meal Preparation 运行证据](../evidence/meal_preparation/README.md)。看作业 `86563` 的双环境隔离和 `86898` 的逐材质槽恢复。这里验证的是 Meal 当时提交的方案。 |
| 一个小物体从素材交付到 A4／A5 怎么分工 | [Charger 接入与检查方法](../CHARGER_A4_A5.md) · [原相机对照图和结构化结果](../evidence/charger_a4_a5/README.md)。充电器主体换色，两根插脚应保持原材质。 |

## 先准备一张方案表

从自己家族的 catalog 抄实际 ID，把预期外观写成能看图核对的描述。列清哪些任务或阶段会加载该物体、哪个部件要变、哪个细节要保留。下表填写的是家具的例子，做其他家族时换成自己的对象和入口。

| 任务 / 对象 | 请求 ID | 预期变化与保留项 | 运行时实际 ID | 同机位原帧 | 结果 |
| --- | --- | --- | --- | --- | --- |
| LayFlatPanel / 板件 | `original` | 原生板面、标签与条码 | 填回合记录 | 填图链接 | 待填 |
| LayFlatPanel / 板件 | `variant_4` | 琥珀橙饰面，标签与条码保留 | 填回合记录 | 填图链接 | 待填 |

**素材作者先交**方案表、部件绑定、预览和最短复现命令；预览注明是模型查看器还是正式任务。已有任务接入或自测的，把证据一并附上。正式任务验证由 Dennis 统一安排，作者可以先发素材 PR。[团队分工与交付说明](../TEAM_APPEARANCE.md)

## 正式短检怎么做

1. **建原生基线。** 记录提交 SHA、任务 ID、平台和后端。关闭外观，固定 seed、初态、相机和光照，保存原生 RGB 与状态。再开启外观并显式选择 `original`，对照同一对象的材质、初态和画面。若原生运行本身有微小波动，先用两次原生运行量出差异并记录。
2. **逐个显式点名十款（A4）。** 对每个实际加载该物体的入口或阶段，在相同条件下逐个 reset 到指定 ID。核对“请求 ID → 回合实际 ID → 材质槽／贴图 → 图中目标部件”。从每款切回 `original`，对照基线。若接口支持随机选择，再用同 seed、同配置、同 reset 顺序重建两次，对比实际方案序列。若物体在图中太小或被遮挡，补固定机位近景，或用与 RGB 对齐的实体分割只统计目标像素；瓶外摆拍等诊断图单独标明。
3. **用两个环境验证局部 reset（A5）。** 让 env0、env1 先用不同方案，只 reset env1 并切回原版。核对 env1 的材质和目标区域 RGB 确实恢复；对比 env0 重置前后的物理状态、材质、方案记录及各路 RGB，有独立随机流时也核对它。交换 env0／env1 再做一次。保存选中与未选中环境的前后图、数值差和通过判据。
4. **确认改动只影响外观。** 在同 seed 下对照原生与候选的机器人及物体初态、碰撞、质量、关节或接触参数，以及初始任务判定。若改到了物理或 reset 路径，用相同动作序列短步对照状态、奖励和判定。将完整机器人任务成功率单列为“已测”或“未测”。

## 从哪里开始跑

在仓库根目录可以先跑下面的家具静态示例，它会列出 11 个 ID 和三个任务，纯 CPU，无需启动仿真。自己的家族应使用对应的 catalog、任务入口和检查器。

```bash
python -B tools/variation/check_furniture_appearance.py --static
```

家具的 Windows 实景来自 SAPIEN `3.0.3+dexarena.gpu1.wininterop5`。Server 3 在 2026-11-19 的独立预检中，受检 Linux 环境缺少家具局部 reset 所需的原生接口；复测家具前先按 issue 检查实际环境。同一服务器上，Meal 已有自己的双环境实测，可参照其脚本组织其他家族的验证。正式渲染使用本次获批的资源和输出路径。[家具 SDK 与运行命令](../../../tools/variation/sapien_sdk/README.md) · [Server 3 复验记录 #18](https://github.com/DennisXu626/DexArena-Variation/issues/18) · [Meal 隔离检查器](../../../tools/variation/check_meal_parallel.py)

**回交给 Dennis** 时发一个 PR 链接。素材 PR 附方案表、原版＋十款同条件预览及复现方式。正式短检完成后，执行者在同一交付中补上任务实景、双环境 reset 的前后证据、实测提交 SHA、命令、seed、后端和结果 JSON。某个入口受阻时，标上首个失败和仍未测的项目即可。
