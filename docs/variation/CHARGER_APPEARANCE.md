# Charger 外观 Variation 实施与验收

## A1 部件清单

Charger 由三个箱体组成，构建为一个动态刚体。三个箱体分别添加视觉形状和对应的碰撞形状。本体和插脚组分别使用一个渲染材质，两根插脚在构建时共用同一个 `prong_material`。

| 部件 | 视觉形状与局部位置 | 原版渲染材质 | PhysX 接触材质 |
| --- | --- | --- | --- |
| 本体 | 1 个箱体，尺寸 80 × 70 × 56 mm，中心在刚体原点 | `body_material`，RGBA `[0.72, 0.75, 0.80, 1.0]`，粗糙度 0.09，金属度 1.0 | `hard_plastic` |
| 插脚组 | 2 个箱体，每根 4.4 × 28 × 24 mm，中心为 `(±22, 0, −40) mm`，沿局部 −Z 伸出 | `prong_material`，RGBA `[1.0, 1.0, 1.0, 1.0]`，粗糙度 0.06，金属度 1.0 | `metal` |

两组都属于用基础色、粗糙度和金属度描述的材质表面。当前构建没有外部 Mesh、贴图或材质文件引用，也没有定义标签材质槽。箱体 UV 的分布、贴图方向和接缝留待采用贴图时实测。

两根插脚的中心间距为 44 mm。外观对照图要能辨认插脚轮廓、间隙和朝向。几何尺寸、局部位姿、碰撞形状、密度和接触材质是后续 A4 回归的基线。当前结论来自源码，任务相机下的辨识度见 A3 验收记录。

[箱体构建与材质绑定](../../tasks/drawer_plug/drawer_plug_long.py#L692)

## A2 方法对比与首批选型

| 方法 | 预期效果 | 人工适配成本 | 来源与使用范围 | 当前结论 |
| --- | --- | --- | --- | --- |
| 原贴图定向改色 | 保留源图细节，调整指定区域颜色 | 需要可编辑源图及区域遮罩 | 当前 Charger 构建无源贴图 | 不适用 |
| 程序材质参数 | 用基础色、粗糙度和金属度改变本体色调与反光 | 低。调整数值后用任务视角筛选 | 使用仓库现有渲染材质接口和项目自定参数，适用于本体及插脚组 | 选为首批方法 |
| 许可清楚的现成材质 | 可增加表面纹理与细节 | 需筛选素材，检查比例、方向和箱体接缝 | 尚未选定资源。采用时记录来源、许可、署名及再分发条件 | 作为贴图候选 |
| 生成纹理 | 可定制表面图案 | 需筛选少量候选并调整方向和接缝 | 采用时记录生成来源及使用条件 | 有明确图案需求时再评估 |

首批保留原版，以暖白哑光、深蓝缎面和铜色金属作为三个本体候选，插脚组采用原版材质。用相同相机、光照和 seed 渲染四套方案，比较本体颜色、反光和插脚辨识度。建议先用 `InsertPlug` 的桌面初态检查插脚，再用 `PickCharger` 核对抽屉场景下的效果。首批候选的实测与人工审查结果见 A3。

## A3 首批外观方案与验收

2026-11-13 人工审查通过。保留原版及暖白哑光、深蓝缎面和铜色金属三套方案。审查确认四套本体外观有足够区别，两根插脚的轮廓、间隙和朝向清楚可辨。插脚组统一使用原版材质。

任务为 `DrawerPlugInsertPlug-Sharpa-v1`。四套方案使用同一次 reset（seed 7），分别在固定任务视角和斜侧视角出图。任务全景中充电器占画面较小，斜侧视角更适合核对双插脚。静帧主要支持颜色、明暗和轮廓对照。运行证据为 Slurm 作业 `71381` 的八张原图、两张对照图和 `manifest.json`。

[方案目录与部件参数](../../tasks/assets/variation/drawer_plug/v1/catalog.json) · [预览脚本](../../tools/variation/render_charger_preview.py)

## A4 真实任务接入与验证交接

实现待继续，运行验收由 Dennis 负责。现有 A3 脚本在同一个 InsertPlug 场景内切换预览材质。A4 要把四套方案接入 PickCharger 和 InsertPlug 的任务配置，覆盖固定选择、从指定集合随机选择、回合内固定以及实际方案 ID 和目录版本记录。

- 在两个任务上分别核对固定方案与实际材质。随机结果应来自配置集合，同一配置、seed 和 reset 顺序应复现相同的方案序列。
- 对照同 seed 的原版与变体，比较本体和插脚尺寸、局部位姿、碰撞、接触材质、质量与惯量。检查取出放置和双插脚插入的成功判定。
- 在 PR 中记录测试任务、命令、环境版本、样本和实际结果。状态触发检查与机器人完整执行的结果分别注明。

## A5 双环境局部 reset 验证交接

待 A4 实现后由 Dennis 执行。让 env 0 和 env 1 使用不同方案，保存各自的材质值、物理状态和渲染帧。仅重置 env 1 并切换到第三套方案，确认 env 1 的材质与记录匹配新方案。比较 env 0 自身 reset 前后的本体材质、插脚材质、物理状态和画面。比较时使用固定相机，期间不做物理步进。

如需提交 GPU 验证作业，按团队 pair-slurm 规范在提交节点核对 Monica 的显存和 Shard 余量，指定物理 GPU Index，以一次短时 `srun` 或 `sbatch` 运行。

## A6 人工审查流程

由同学人工完成部件映射、选材、方案编号与版本记录。用相同初态、视角和光照导出原版与候选对照图。审查人逐套核对任务相关细节并记录保留、调整或替换的结论。调整后按相同条件重新出图。待另一种类型的任务物体按同一流程实际复做并记录结论后验收 A6。

## 推送分支与请求审查

当前 PR 范围为 A1–A3。已有 InsertPlug 首帧对照及人工验收。A4 实现、A4/A5 运行验证和 A6 跨资产复做列为后续工作。提交前从团队仓库根目录执行以下命令，逐一暂存本次交付文件。

```powershell
git switch feat/charger-appearance
git status --short --branch
git diff --check
python -B tools/variation/check_static.py
git add -- docs/variation/CHARGER_APPEARANCE.md tasks/assets/variation/drawer_plug/v1/catalog.json tools/variation/render_charger_preview.py
git diff --cached --check
git diff --cached
git commit -m "Document and preview Charger appearance variants"
git push -u origin feat/charger-appearance
```

在团队仓库的 GitHub 页面发起 PR，base 选 `main`，compare 选 `feat/charger-appearance`，在 Reviewers 中指定 `@DennisXu626`。按 PR 模板说明四套方案、静态检查结果、作业 `71381` 的实测范围与人工审查结果，并附同视角对照图或团队可访问的证据链接。图片和运行输出作为审查附件或链接提供，Git 提交包含文档、配置和预览脚本。Dennis 审阅批准并解决讨论后，按团队约定 squash 合并。

[团队贡献规范](../../CONTRIBUTING.md) · [PR 模板](../../.github/PULL_REQUEST_TEMPLATE.md)
