# PR8-R2 核对与整合收尾

**待独立审验负责人查收，执行层未批准、未合并。** Dennis转发的PR8-R2收窄并替代R1补交要求；保留[R1审阅](https://github.com/DennisXu626/DexArena-Variation/pull/8#pullrequestreview-5918176986)历史，最终验收结论以[PR #8](https://github.com/DennisXu626/DexArena-Variation/pull/8)后续审阅为准。

## 提交对应性

- 上轮已审及本轮起始head：`928fb143bdeca0d875b0a6319b7f3bee2def488f`；base/main：`acd6ba232b8da7a97fd313aa3df8a9f595fd55e0`。
- 提交前刷新发现作者新提交`59f97ba43f82d0186024c2992685dc701f49dce2`，本轮已停止旧候选提交，核对新增22文件差异并在新head上整合。新补档全部保留；本执行层的最终提交只含文档和精简证据，不再重复作者已完成的清理。
- 59f97ba相对928fb143的生产及现有仿真验证脚本变化仅为三处EOF空行及一处警示注释。四文件AST相同；catalog、纹理生成及三个短任务文件blob保持。归档检查器只新增`implemented_pending_review`状态以匹配索引，未改仿真行为。
- [本轮静态核对及哈希映射](pr8-r2-static.json)记录928fb143→59f97ba→本轮候选的文件身份；[作者清理映射](source-cleanup.json)保留历史LF哈希。最终head见PR收尾留言；本轮检查按59f97ba与候选blob冻结，避免文件内自引用提交号。

## 每条结论与证据

| 拟交审验的限定结论 | 证据／身份 | 边界 |
|---|---|---|
| 五对象 original＋两候选及四任务接入已交付 | [唯一catalog](../../../../tasks/assets/variation/meal_preparation/v1/catalog.json)、[实际绑定与用法](../../MEAL_APPEARANCE.md)、R1源码审阅及PR四图 | 默认程序午餐盒；plate_0、spoon_16、bagel_5、tomato_2；三个Sharpa短任务＋一个Sharpa长任务。四图已由R1查看，本轮不重渲染 |
| 默认路径、物理常量及成功／奖励定义保持已审实现 | R1静态审阅；四个清理文件AST相同，catalog及其它生产文件blob不变 | 静态不变与历史局部reset状态对照有据；不据此宣称完整机器人或动力学全域成功 |
| 固定方案局部reset隔离已有限定证据 | [86563结果](job-86563-results.json)、[源码及环境身份](runs.json)；实际运行引用796ed7a，R1已核对与928fb143生产文件对应 | 四任务各2环境、seed 7，关闭／开启对照，仅reset env1且无物理步进。状态最大差2.384185791015625e-7；开启组短任务每路最多1通道差1级，关闭组最多3通道差1级，长任务0。未放宽状态1e-6及每路最多8通道差1级的原容差 |
| 恢复original与原生基线一致已有归档核对 | [86898逐槽及RGB](job-86898-results.json)、[R1核对记录](pr8-r1-evidence-audit.json) | R1已核对12+22+22+22=76槽材质／纹理数据和恢复后env1真实RGB差异0，不重跑；不以方案标签或getter替代RGB |
| 随机选择／记录逻辑可复现 | [R1 CPU记录](pr8-r1-selector-cpu.json)，928fb143原始MealAppearance类AST，NumPy 2.4.2 | 32轮相同seed／配置／环境数／reset顺序，未选env0 RNG保持；空渲染绑定，仅CPU逻辑。59f97ba AST相同复用，未重跑；随机方案真实GPU路径未测 |
| 新增补档能够按字段追溯 | [收据摘录](receipts.json)、[运行身份](runs.json)、[资产清单](asset-identity.json)、[源清理映射](source-cleanup.json)及本轮静态记录 | 核对文档内部对应、时间算术、新归档脚本／manifest哈希及实际模型标识；执行层未再次登录Monica或直接读取远端资产，明确区分作者转录与独立调度查询 |
| 86264旧回放保留历史参考价值 | [历史结果](job-86264-results.json)、[归档脚本](job-86264-inputs/check_meal.py)、[绑定脚本](job-86264-inputs/render_meal_objects.py)、[两份catalog](runs.json) | 旧acd6ba2＋独立预览，不用来证明当前接入完整运行。开盒首次成功第74步；放面包／舀番茄未复现最终成功，长任务受控状态；不要求重新完整回放 |

## 补充资料的使用方式

- `receipts.json`为作者从已认证Monica收据作的限定转录，带脱敏实际命令、日志哈希／结果行及保留范围。摘录报告86264／86563／86898为COMPLETED、退出码0:0，分配时长108／118／52秒，每个命名GPU索引数1、共享Shard数1；合计278命名GPU索引分配秒。不是设备活跃秒数或独占整卡秒数，不据此增加本轮用量。计账见[本轮及历史资源](pr8-r2-costs.json)。
- `runs.json`补充86898与86563相同部署目录、日志模型路径及留存八生产文件的哈希／mtime证据。mtime早于两次启动；这些支持关联，但不是86898当次独立生产checksum manifest，后者仍无法追溯。
- `asset-identity.json`列出程序盒及plate_0／spoon_16／bagel_5／tomato_2的MJCF、visual／collision mesh、MTL和源贴图身份。该清单为运行后从相同安装路径补采；原版像素可与86898归档关联。运行时几何逐文件哈希和上游revision仍不可追溯；历史HF revision只作调查来源，不当作本轮运行身份。未发现关键绑定或资产选择的具体冲突，不要求完整资产包或重哈希。
- [86157 manifest](render-manifest-86157.json)与[86234 manifest](render-manifest-86234.json)按各自旧预览范围使用，保留场景、seed、相机及版本信息，不自动绑定当前四张PR拼图或证明正式接入完整运行。
- 已有实际命令见`receipts.json`的`receipt_command`及`runs.json`的86563 `batch_archive.command_excerpt`。变量占位是作者脱敏，不伪称为本机执行记录。运行环境引用Python3.10、SAPIEN3.0.3、ManiSkill3.0.0b22、Torch2.12.0.dev20260408+cu128；86563／86898为PhysX CUDA、lyg0295 G0。86264的CPU物理后端不代表渲染无GPU用量。

## 状态与交接

- **通过／复用**：R1已关闭的源码身份、76槽恢复与RGB、四图、CPU选择逻辑；本轮新head影响分析、补充资料对应性、受影响文档链接、JSON／CSV及状态计数、AST和实际base到候选空白检查，详见静态记录。
- **功能失败／阻断**：未识别到新的具体功能缺陷或本限定范围必须新增的验证缺口；最终head与受影响部分仍由独立审验负责人复核。
- **文档收尾**：作者已更新能力表／导航／对象索引与格式；本执行层修正README首段仍写两家族的旧范围、补五对象说明及集中索引，所有原补档保留。
- **未测**：随机方案真实GPU路径、更多环境／手型、PartNet午餐盒、完整机器人长任务成功、A6、训练和大规模性能；未到达的新运行阶段不适用，本轮没有启动作业。
- **无法追溯／非阻断**：设备活跃GPU秒数、完整状态流转与历史清理记录、86898当次独立生产manifest、运行时逐文件几何hash／上游revision、当前四拼图与旧render manifest的完整对应链。收据摘录有终态，本轮未独立查询当前远端队列，不声称所有相关作业当前均已结束。
- **作者补充：无需作者补充。** 已查当前PR／留言／R1审阅、22文件新增差异、runs及三份结果、收据、资产与渲染manifest、本地R1归档。没有材料同时满足确实缺失、仅作者持有、当前限定验收不可替代地依赖三个条件；不把泛化资料缺失列为阻断。
- **资源与提案**：新增GPU0秒、新计算作业0次，未启动仿真／训练／大型下载；无新增运行提案。短时静态检查，无后台任务；R1原件未覆盖，无服务器清理。

GitHub身份DennisXu626，可见仓库权限admin；**行为上禁止合并，平台权限尚未隔离**。执行层未提交APPROVE、未改权限或保护规则、未合并。报告由Dennis转回审验负责人，本轮完成后停止。
