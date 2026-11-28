# PR41 R3 返修交接

## 目标与改动

上一轮问题：在 `fd6340818c195adaedc970acc4ac5668cc9bda2e`，同一物理步
保存后原样读档，第一次 evaluate 会将拾取 hold 从 7 加到 8，或倒入 hold
从 9 加到 10，并提前锁存成功。新收到的 `PR41-R3_AUTHOR(1)` 仍针对该版本。

生产修复提交为 `1d5151bf61b8586c1905f36e54f554ca50647001`，目标分支 main，
PR41 原 base 为 `6e3467b537bd67de3aeadb6758dc46d54170b96f`，依赖已合入 PR12。
本次补充提交仅扩展检查脚本和归档，不再修改生产逻辑，也不声称整合了更新的 main。
实际源码、脚本身份和环境见 [receipt.json](receipt.json)。

修复文件 `tasks/table_cleaning/table_cleaning_long.py`：新存档增加逐行布尔字段
`table_clean_hold_counted`，保存本步是否已计数；恢复时映射到当前控制步，避免重复累计。
尚未计数的帧仍正常计数，不统一减一；保留七字段旧任务状态、无任务状态输入和
`value` 包装读取。旧存档缺少处理标记，沿用原有首次读取行为，无法追溯其保存时机。
此逻辑位于 Pick、Dump、Long 共用基类，8/10 步门槛、运动缓存失效和未选行保护不变。

最小复现：仓库根目录执行
`python -B tools/variation/check_table_cleaning_hold_restore_cpu.py`。
检查调用真实存取档方法、Pick evaluate 和 dump success 辅助函数；物理接口为 CPU 替身。
本次不涉及新增素材、配色或资产。

## 实际验证

所有本轮命令、退出码、平台及源码 SHA-256 记录在 [回执](receipt.json)。
两环境、确定性人工条件，无随机 seed、无资产加载、无 GPU 作业。

| 验了什么／状态 | 实际受测版本与条件 | 判据与实际结果 | 原始证据入口 |
|---|---|---|---|
| 原审阅反例／通过 | 生产代码 1d5151b，CPU，2env | 两个 equivalent 均 true，原样回载不提前成功 | [新目录脚本输出](reviewer-after.json) |
| 保存后继续与连续执行／通过 | 生产代码 1d5151b，扩展检查器身份见回执 | 41例，双向选行、原步号及不同步号、已计数／未计数、原张量／包装、旧格式／无任务状态、全量首次恢复 | [逐用例读回](hold-restore.json) |
| 原 1 cm 位移／复用通过 | 1d5151b，ManiSkill b22 源码，CPU 替身 | 48例，恢复后运动缓存重算；生产与该脚本均未变化 | [48例原始结果](../pr41_r3/state-restore.json) |
| 局部 reset 隔离／复用通过 | 1d5151b，ManiSkill b22 源码，CPU 替身 | 4项，结果身份见回执 | [原始结果](../pr41_r3/isolation.json) |
| 其余 CPU 回归／通过 | 生产代码 1d5151b，本轮工作树 | reset 11项、单环境64组最大差0、hold重复读取均通过 | [reset](reset.txt)、[单环境](single-env.txt)、[hold](hold.txt) |
| 静态与档案／通过 | 本轮工作树 | 脚本语法、目录与链接及素材档案检查通过 | [静态](static.txt)、[档案](archive.txt) |

原样保存已计数的帧时，选中行的关键读数如下。未选行始终 hold=0、success=false；
正向只恢复 env0 观察 env1，反向只恢复 env1 观察 env0，逐行完整值均在 JSON 中。

| 判定 | 保存 | 刚回载 | 同帧连续3次读取 | 下一控制步 |
|---|---|---|---|---|
| 拾取 | 7 / false | 7 / false | 7 / false | 8 / true |
| 倒入 | 9 / false | 9 / false | 9 / false | 10 / true |

“下一控制步”由 CPU 用例递增 `_elapsed_steps` 表示，并非新物理仿真。
旧版的原触发输出见 [reviewer-before.json](../pr41_r3/reviewer-before.json)，其复用哈希
亦在回执中。尚未计数的存档首次读取增加一次，与连续执行完全一致。

## 剩余问题与返修交接

修复链：同物理步原样恢复重复计数 → 1d5151b 保存／恢复处理标记 → 原触发
用例不提前成功 → 本次补充41例逐帧读数与身份清单。

本次生产代码及1 cm检查器与实测提交1d5151b按LF规范化逐字节一致；仅
`tools/variation/check_table_cleaning_hold_restore_cpu.py` 增加原步号和逐帧记录，
另新增本目录证据文件。用户提供的 AGENTS.md 保持原样，不混入本修复提交。

未新增GPU作业（提交次数0、GPU秒0）；未宣称完整策略轨迹或真实仿真存档恢复通过。
历史138555/138600证据只按原身份保留，不能代替本次改变路径的实测。
后续由 Dennis 对新head组织独立复核；无需作者重跑整套GPU。
