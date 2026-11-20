# PR12-R1 修正与自测交接

本轮为作者修正，待 Dennis 独立审验；未批准或合并 PR，未 commit／push。

## 版本与改动

- 受审／当前已提交 head：`c40151f5b52d40697e60429cf31fe752b2c57c5d`。
- 原开发基线：`acd6ba232b8da7a97fd313aa3df8a9f595fd55e0`。
- 本轮 fetch 后的冻结 main：`aee41a3439287a17ce9d4c14c6320fa6f5b4579d`，与 R1 指定整合基线一致。本轮未将 main 合并到作者分支；在临时整合树覆盖完整 PR 改动后执行检查。
- 新 head：待作者提交产生，不虚构未提交版本哈希；修正源码和材料身份见[本轮 manifest](evidence/table_cleaning/r1_manifest.json)。若提交后 main/head 移动，需重新判断受影响范围。

生产改动只有 `appearance.py` 和 `table_cleaning_long.py`：提取无副作用的 `resolve_requests`；公开 `TableCleanBase.reset` 在任何基类 reset 调用前解析全部选中环境。配置合并仍为构造器全局→构造器 per_env→reset 全局→reset per_env。材质应用继续调用同一解析器，合法方案的材质计算和回合记录不改。

更新静态桶注释：单环境默认每次重建确定桶位置；多环境默认建场逐环境确定，局部 reset 保留静态桶位置。未变几何、碰撞、质量、关节、判定或合法路径布局算法。

## 新增 CPU 自测

公开 reset 与适配器方法由当前源码 AST 直接提取执行；只替换外部 BaseEnv／渲染对象，不导入 SAPIEN、torch 或仿真器。

- [reset_cpu.json](evidence/table_cleaning/reset_cpu.json)：11 项通过，覆盖全量 reset 末行未知 ID、仅 env1 未知 ID、配置未知 ID、单环境错误、合法／关闭路径、覆盖顺序、局部记录及恢复 original。
- 对非法请求，基类 reset／模拟随机抽样／模拟状态写入次数均为 0，记录和材质不变。这是 CPU 调用顺序证据，不是错误发生后的仿真器实测状态差值。
- [旧版反例](evidence/table_cleaning/old_reset_counterexample.json)：执行受审 head 的公开 reset，同一输入会进入基类替身并产生三项事件，证明探针能区分修正前后。
- 独立的 `table_cleaning_contract.py` 固定验收 ID→部件→颜色关系，不参与运行选材。互换两套合法 catalog 或把实际 variant_2 材质冒作 variant_1，两项反例均被拒绝。未来 GPU 检查将逐部件验证颜色／粗糙度及从原始像素独立计算的糖块纹理身份。
- [single_env_cpu.json](evidence/table_cleaning/single_env_cpu.json)：执行固定原版 Git 源码和当前关闭外观路径的真实初始化方法，以 CPU actor／tensor 替身比较 32 seed × noise 0／.02，共 64 组；桶位置、簸箕与糖块布局、机器人 qpos 和 RNG 消耗一致（root 调用沿用相同常量），最大数值差 0。替身不验证真实场景构建、机器人加载或动力学。

复现命令（仓库根目录，CPU）：

```bash
python -B tools/variation/check_table_cleaning_reset_cpu.py
python -B tools/variation/check_table_cleaning_single_env_cpu.py
python -B tools/variation/check_table_cleaning_preview_cpu.py
python -B tools/variation/check_static.py
python -B tools/variation/check_appearance_archive.py
```

## 复用 90644：编号、部件与原图

未重渲染。复用原始本地归档，非重新下载 PR 附件；[原 manifest](evidence/table_cleaning/preview_90644_manifest.json)、[语义复核](evidence/table_cleaning/preview_semantics.json)、[材料 SHA-256](evidence/table_cleaning/reused_file_hashes.json)随本轮交付。原图仍需在原 PR 保持可访问，不能只提供个人路径。

| ID | 簸箕主体 | 桶框 | 糖块 | 对应图列 |
|---|---|---|---|---|
| original | 原蓝色 | 原深灰 | 原白灰纹理 | 左 |
| variant_1 | 哑光青绿 #2D746E，粗糙度 .84 | 暖浅灰 #B0A79B | 浅粉 | 中 |
| variant_2 | 砖红 #A64D3C，粗糙度 .51 | 深蓝灰 #384F6A | 淡蓝 | 右 |

| 原图 | 能核对的部件 | 限制 |
|---|---|---|
| pan_loaded_comparison.png | 簸箕主体颜色、握套保留、粉／蓝糖块 | 不包含桶，反光只能作视觉辅助 |
| bin_floor_comparison.png | 暖灰／蓝灰桶框、桶身网格保留、粉／蓝糖块 | 糖块是实际 DumpDustpan 场景内受控摆放；不是机器人倒入成功 |
| pick_scene_comparison.png | 三对象整体初态、配色关系 | 簸箕部分裁切、糖块偏小，判色以两张近景为主 |

三张归档图已由助手逐张复核，原预览人工审查沿用先前用户意见；本轮没有新增人类验收。manifest 四视图共 8 个候选记录的主体／桶框颜色和粗糙度符合独立 ID 契约，同视图初态和相机一致。糖块粉／蓝由原图核对，原始纹理身份有记录；本轮未从原模型重新生成历史像素。预览平台为单环境 CPU 物理＋GPU 渲染，不是双环境 CUDA 仿真。

## 复用 90672：三入口限定双环境

原 [summary.json](evidence/table_cleaning/summary.json)保持不变。PickDebris、DumpDustpan、Long 各两环境，显式 variant_1／variant_2；关闭外观对照采用同次提交的适配实现，不是未经改动旧版的双环境对照。env1 恢复 original、env0 状态／材质／记录／RGB 的已有成功路径证据保留，具体差值按原 JSON，最大状态差约 1.19e-7。

原检查仅证实两套均发生变化；新增逐 ID 语义断言没有冒充在 90672 上已执行。历史图／manifest 的离线复核和新增 CPU 对调反例补齐本轮语义证据。采集 reset 快照后只有一步零动作动力学，说明该步能执行，不证明长时稳定、完整任务成功或全部判定分支。未实现集合随机；不外推其它手型／规模。

## 静态、费用和交接

冻结整合树的两个仓库原始静态命令及本轮 CPU 结果见[整合检查](evidence/table_cleaning/integration_checks.json)。临时整合采用单次命令的 core.autocrlf=false 检出 LF，不修改任何全局／仓库 Git 配置；避免 Windows CRLF 影响旧 JSON 字节哈希。当前作者的 Windows 原工作树仍可能因旧 Cabinet JSON 的 CRLF 产生原归档检查哈希错误；本轮通过的是上述 LF 整合树上的原始命令，未修改检查脚本绕过断言。

能力索引本轮不把 Table Cleaning 提前标验收通过；本基线仍为待适配／待审，本交付说明明确 PR12 候选及证据边界。其它家族 main 中的已合并内容不被覆盖。

本轮新增 GPU 秒 0、作业提交 0、未连接服务器运行任务。90644／90672 为复用历史预算；90672 原交付记载 31 秒分配，不把它改称实际 GPU 计算秒；90644 费用本轮未独立取得，不补猜测值。原始资产、图片、缓存不提交，仅归档小型 manifest、结果、文件哈希和方法说明。

作者后续在原分支提交并 push 到 PR12，回填新 head，重新请求 Dennis 审阅。若 main 移动或冲突处理修改了本家族合法路径，需重新评估证据是否可复用。
