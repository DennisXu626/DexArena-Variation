# PR19-R1 作者修正与自测

本轮仅完成作者修正与 CPU 核对，待审验层刷新新 head 后安排冻结版本的 Server 3 GPU 验证；建议 G7，但尚未提交作业。未批准或合并远端 PR。

## 版本与 main 整合

- 受审 head：`fc028483b5d865c05ee6e7e18b95975c836c9935`。
- 实际整合的 main：`aee41a3439287a17ce9d4c14c6320fa6f5b4579d`，本轮 fetch 后未移动。
- 原 Git 分叉点：`acd6ba232b8da7a97fd313aa3df8a9f595fd55e0`。
- 作者分支：`codex/juice-preparation-appearance`；本地已执行 `git merge --no-commit --no-ff origin/main`，五个冲突均已解决，等待用户提交合并及修正后产生新 head。
- 逐文件身份及相对 main 的改动清单见[本轮 manifest](evidence/juice_preparation/r1_manifest.json)。不将旧 head 冒作新版本。

五个冲突文件以 main 内容为基准保留已合入家族，只加入 Juice 待审候选：README、对象总索引、objects.csv、runtime_mapping.json、STATUS。逐行保留其它家族 CSV 字段和状态，重新统计 42 个对象：accepted_pilot 11、pending_adaptation 20、external_pending 4、implemented_pending_review 3、no_visual 3、not_loaded 1。Juice 四对象为 external_pending，不提前标正式通过。[PR #19](https://github.com/DennisXu626/DexArena-Variation/pull/19)链接已回填。

工作区原有一个异常命名的未跟踪文件已保留，未读取内容、未加入暂存；提交时不要使用 `git add .`。

## R1-1：错误请求统一预校验

`JuiceAppearance.resolve_requests` 只解析和校验，不写材质或回合记录。构造器全局→构造器 per_env→reset 全局→reset per_env 的覆盖顺序保持。

四个直接 BaseEnv 任务继承同一 `JuiceResetMixin`；CloseFridge、Long 通过父类继承。公开 reset 在调用 BaseEnv 前验证全部选中行；apply 自身也先检查所有方案和绑定，再进入材质写入循环。合法路径配方及 original 恢复计算不改。

真实 CPU Torch 自测从公开 reset 进入，六任务各覆盖全量末行非法、局部 env1 非法，共 12 组：外部基类 reset、随机抽样、状态写入替身均未被调用，任务缓冲、材质代理和记录保持。另复现冻结旧 apply 的“env0 已写入／env1 报错”反例，新 apply 拒绝整个请求。合法覆盖顺序、original 恢复和默认关闭路径通过。

这是未知方案的提前拒绝保障，不宣称其它任意初始化或渲染异常具有事务回滚。

## R1-2：局部 reset 不推进未选行

公开 reset 的作用域保存选中行掩码，并在 finally 恢复。正常 step 时不设置该掩码，沿原门槛推进。

- PressButton：按住计数、成功锁存只更新选中行；返回的 counter／progress／success 也与保护后的状态一致。
- OpenFridge／CloseFridge：门稳定计数与接触／成功锁存使用选中行。
- PlaceLid：拾取、转运、入座、释放、成功锁存及成功计数保护。
- AppleToBlender：路由锁存、稳定计数、成功锁存以及苹果有限差分历史保护。
- Long：五阶段 active mask 与 reset 行掩码相交；阶段、计数、手部锁存及苹果历史均保护，阶段顺序不变。

CPU 对照使用真实 Torch 2.6.0+cpu，AST 载入实际公开 reset、evaluate 和状态 helper；替换的是 BaseEnv／几何／接触／渲染输入，不导入仿真器。六入口、双向选择、Long 五阶段，共 20 组临界 reset 通过。按钮未选行计数保持 3，success 保持 false，progress 为 .75；离开 reset 后正常 evaluate 仍从 3 推至 4。其它任务也检查未选缓冲及正常求值推进。

冻结旧 PressButton.evaluate 的 3→4 反例仍能重现；异常退出也会恢复 reset 作用域。生产类继承关系另行核对，避免只测试一个未被正式入口使用的 mixin。

## R1-4：方案 ID 与图片／图注绑定

预览脚本按 `(scheme_id, label, image filename)` 显式对应，列头显示 ID。JSON 键顺序改变只调整展示顺序，不会把 1 号和 2 号标签对调；第四个未知 ID 会显示其 ID，不会被 zip 截掉。

CPU 样例将顺序改为 variant_2、original、variant_1，并追加第四个方案，检查列头与文件对应、四列均存在、每列底图像素正确。只生成临时纯色测试图，不当作真实资产预览。原六组真实任务对照和四张 Long 图保持；本轮不重渲染，也不新增人类审美验收。

## 自测命令与结果

```bash
python -B tools/variation/check_juice_r1_cpu.py --output docs/variation/evidence/juice_preparation/r1_cpu.json
python -B tools/variation/check_static.py
python -B tools/variation/check_appearance_archive.py
git diff --check
git diff --cached --check
```

[CPU 结果](evidence/juice_preparation/r1_cpu.json)记录 10 组 unittest（含上述多任务子样例）。[仓库检查](evidence/juice_preparation/r1_checks.json)保存实际命令和平台。Windows 原工作树的既有 JSON 可能受 CRLF 字节哈希影响；最终仓库静态检查在由本次整合索引导出的 LF 快照上执行，不修改原静态检查来绕过断言，也不改系统 Git 换行配置。

## 继承的证据与尚待 GPU 复验

历史 123675／123676 的结果、signatures、manifest、收据及图片哈希保持原文件，不覆盖成新版本结果。它们支持受审版本初态附近的双环境隔离、73 槽恢复、物理签名及16步零动作；不支持本轮新增临界 reset 路径已在模拟器通过。

新 head 冻结后，请审验层确认并交执行层验证：六入口真实公开 reset 选择两套颜色、两方向局部 reset／原版恢复、未选行临界计数与阶段／历史状态、物理／材质／RGB隔离。G7 需在提交前重新核对 Monica，历史截图不保证届时仍可用。执行层只验证并报告，不改代码、不批准或合并 PR。

本轮新增 GPU 作业 0、GPU 秒 0，没有连接服务器运行任务，没有安装依赖。CPU 替身结果不扩展为真实物理状态或完整机器人任务成功；随机模式、其它手型／规模、长时压力仍未验证。
