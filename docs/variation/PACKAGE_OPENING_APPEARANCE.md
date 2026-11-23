# Package Opening 外观试样

交付三类对象的原版与两套外观，覆盖开包装、取苹果和长任务。

| 对象 | 原资产与绑定 | 候选 |
| --- | --- | --- |
| 包装盒 | `package/mobility.urdf`。盒身、双翻盖、内底板和两个程序提拉片独立绑定。原版 `original-18.obj` 粉色材质槽保留，实景表现为盒身下沿色带。 | 暖棕牛皮纸、蓝灰纸盒 |
| 苹果 | `robocasa/objects/objaverse/apple/apple_0/model.xml` 的 `defaultMat.011`，沿用 `visual/image0.png` 和原 UV。按原贴图的色相、饱和度与亮度做渐变掩码，保留果梗和暗部层次。 | 金黄、青绿 |
| 接收盘 | `robocasa/objects/objaverse/plate/plate_1/model.xml` 的 `Material.392`，盘面和盘底共用一套材质。 | 深青亮釉、暖白缎釉 |

无新增几何和 UV。盒子和接收盘使用程序材质。苹果衍生贴图由团队已授权安装的原资产现场生成，衍生贴图的再分发许可未核实。仓库只交付改色配方和参数。

## 真实任务预览

包装盒合盖使用 `PackageOpeningOpenPackage-Sharpa-v1`。开盖、苹果、接收盘使用 `PackageOpeningExtractApple-Sharpa-v1`。每组使用 seed 7，以及固定初态、相机与照明。预览脚本在独立进程内调整视觉材质，各方案使用同一任务代码。苹果和盘子使用正上方略偏的近景。

服务器作业 `86875` 完成四组，共 12 张原图。运行使用 SAPIEN 3.0.3、ManiSkill 3.0.0b22、CPU 物理和 GPU 渲染。脚本核对组内相机、物体位姿和盒盖关节角度的记录一致。对照图由 PR 提交者作为附件提供。

在获授权的渲染作业中，从仓库根目录运行以下命令，其中 `PACKAGE_ASSET_ROOT` 指向团队已安装的 `package_opening` 资产目录。

```bash
python -B tools/variation/render_package_opening_preview.py \
  --catalog tasks/assets/variation/package_opening/v1/catalog.json \
  --assets "$PACKAGE_ASSET_ROOT" --output outputs/package_opening_preview
```


## 青绿苹果修订

作业 `86921` 在真实取苹果任务中复跑苹果近景及盒内全景。方案 ID 仍为 `green`，目录版本为 `package-opening-preview-v2`。新版遮罩把果梗周围的亮黄色果皮纳入柔和过渡，使用较低饱和度的青绿色，保留果梗、暗部和原图表面纹理。金黄苹果和其它对象沿用首轮参数。

## 在任务中选择外观

构造环境时通过 `package_appearance` 启用外观设置。未传参数时沿用原加载路径。

| 方案 ID | 包装盒 | 苹果 | 接收盘 |
| --- | --- | --- | --- |
| `original` | 原版 | 原版 | 原版 |
| `variant_1` | 暖棕牛皮纸 | 金黄 | 深青亮釉 |
| `variant_2` | 蓝灰纸盒 | 修订后的青绿 | 暖白缎釉 |

```python
env = gym.make(
    "PackageOpeningLong-Sharpa-v1",
    num_envs=2,
    sim_backend="physx_cuda",
    package_appearance={"per_env": {
        "0": {"scheme_id": "variant_1"},
        "1": {"scheme_id": "variant_2"},
    }},
)
env.reset(options={
    "env_idx": torch.tensor([1], device=env.unwrapped.device),
    "package_appearance": {"scheme_id": "original"},
})
```

显式指定使用 `scheme_id`。也可通过 `mode="random_choice"`、`scheme_ids=["variant_1", "variant_2"]` 和 `seed` 为每个环境建立独立随机序列。每次 reset 确定方案，回合期间沿用。读取 `env.unwrapped.package_appearance.records` 可获得环境索引、回合编号、方案 ID 和目录版本。

包装盒视觉 OBJ 和 MTL 每个环境用独立的临时副本，保持原文件字节及材质槽，原资产继续用于碰撞。苹果从原始颜色贴图生成两张可缓存的像素数组，每个环境绑定自己的 GPU 纹理，并在原句柄内更新像素。接收盘直接更新各环境视觉材质。

## 回归方法与证据

```bash
python -B tools/variation/check_package_opening.py \
  --assets "$PACKAGE_ASSET_ROOT" --base <base-commit> --output "$OUTPUT_PATH"
```

同一程序分别创建无外观设置的原版环境与启用两套外观的环境。检查渲染网格和 UV、碰撞形状及接触参数、质量和惯量、铰链限位和驱动，以及给定关节和物体位姿后真实评估器输出。任务判定使用受控位姿输入覆盖成功与失败条件。双环境检查仅 reset env1，确认 env0 的渲染、材质和状态保持一致，再逐槽比对 env1 恢复结果与独立原版。输出每个阶段的 JSON、对照帧和带版本、源码哈希、Slurm 作业号的汇总。

### Server 3 G0 实测

Slurm 作业 `87021` 在 `lyg0295` 完成，退出码 `0:0`。基线为 `acd6ba232b8da7a97fd313aa3df8a9f595fd55e0`，外观接入源码以运行时 SHA-256 标识。三项任务各使用 2 个环境、PhysX CUDA 与 GPU 渲染，SAPIEN 3.0.3，ManiSkill 3.0.0b22。[结构化汇总](evidence/package_opening/summary.json)包含源码哈希、阶段判定、隔离差值及计时。逐槽材质签名、原始帧、完整日志和 Slurm 收据随运行证据交付，可在服务器个人作业归档的 `package-opening-appearance-v1/regression/87021` 找到结构化结果与帧，日志为 `regression/slurm-87021.out`。

| 任务 | 成功判定覆盖 | env1 恢复原版 | env0 保持 |
| --- | --- | --- | --- |
| 开包装 | 双盖闭合、单盖超过阈值均失败，双盖均超过 90° 成功 | 21 个材质槽一致，RGB 差 0 | 材质、状态、RGB 完全相同 |
| 取苹果 | 未提取便放盘、偏离盘面或保持不足均失败。提离盒沿后放盘、释放并稳定满 40 步才成功 | 23 个材质槽一致，RGB 差 0 | 材质完全相同。状态最大差 `3.58e-7`，与原版局部 reset 一致。RGB 有 1 个通道差 1 |
| 长任务 | 双盖打开只推进第一阶段，按取苹果与放盘条件完成第二阶段 | 23 个材质槽一致，RGB 差 0 | 同取苹果 |

两套方案的受控任务判定输出均与原版一致。几何、UV、碰撞和质量／惯量、铰链属性及接触材质快照一致。原版恢复覆盖材质属性和贴图像素哈希，各任务的选中环境状态也与独立原版逐值一致。早期作业 `87020` 使用逐字节状态断言，在原版取苹果环境处中断。正式结果同时记录了原版与变体的浮点差值，状态阈值为 `1e-6`。

| 任务 | 构建原版 → 变体 (s) | 热 reset (ms) | 物理 step (ms) | RGB (ms) |
| --- | ---: | ---: | ---: | ---: |
| 开包装 | 1.770 → 1.571 | 9.24 → 9.32 | 465.98 → 465.42 | 5.26 → 5.26 |
| 取苹果 | 1.615 → 1.957 | 11.44 → 11.71 | 271.52 → 272.78 | 4.94 → 4.95 |
| 长任务 | 1.403 → 1.794 | 12.60 → 12.41 | 499.16 → 499.70 | 5.25 → 5.30 |

以上是同一作业进程先跑原版再跑变体的单次构建和 8 次热调用中位数。热 reset 复用当前方案，初次生成贴图和重复切换的代价没有单独计时。任务判定输入由脚本控制，完整机器人开盒和抓取轨迹、更多并行环境及显存曲线留待后续验收。

## PR9-R2核对与档案收尾

限定证据已查收，待最终合并。[方案映射](evidence/package_opening/SCHEME_MAPPING.json)分别记录任务scheme_id、对象recipe ID、env_idx、role和历史图注。无数字方案入口。variant_1为kraft／golden／teal_glaze，variant_2为blue_gray／green／ivory_satin；green保留include_yellow_skin=true。

四张PR图按内容分别为闭盒、苹果、盘子、盒内苹果；第四张盒体仍original，不声称两套开盖纸盒均已视觉验证。预览文件用recipe ID命名，任务接口用scheme_id，两者不混称；执行预览模板必须显式传入上述唯一运行catalog，本轮没有运行预览。未来Windows运行OBJ／MTL临时副本须先核准D盘位置及量级，本轮没有环境导入或临时资产生成。

[本轮记录](evidence/package_opening/PR9-R2.md)复用已关闭32轮检查和既有GPU证据，只补CPU索引映射。

## 扩展到十套（候选）

新增variant_3～10及G7预览见[十套交付](PACKAGE_EXPAND_TO_10.md)。本页原有两套回归证据不涵盖新八套；新增可选苹果亮度映射仍待并行审查。
