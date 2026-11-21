# 三项最小诊断定位（2026-11-21）

用户确认记录ScoopTomato新判据重评，并对Meal开盒、Meal长任务、Package长任务做最小定位。本轮未修改生产任务、物理、reset或正式检查器阈值，也未执行十套全量复验。

## 已确认的重评

ScoopTomato A5按用户同意的腕部相机规则（最大差3、变化通道≤8、变化像素≤5），保存原帧实测2/6/5，选中行原生恢复各路RGB差0，重评20/20通过。旧report不覆盖；正式记录见Meal环境档案tomato_reassessment.json。随机复现仍未测。

## Meal OpenLunchBox 与 Long

125109最简单的实验：关闭外观、始终original、variant_1切回original，三个场景的selected env0各路RGB都与短历史原生基线一致，未复现差41。因此追加125111的单变量历史实验：在同样任务中增加上轮A4的21次reset／渲染，再做同序局部reset。

- history_native：完全关闭外观、同样历史，原生自己在Human(y414,x372)出现max41/3通道。
- history_original：开启但始终original，出现相同像素差。
- history_variant_then_original：按上轮顺序遍历十款并恢复，再做variant_1/variant_2双环境局部reset，也出现相同差。
- 将历史相同的history_native与history_original、history_variant_then_original逐帧比较，两个入口所有任务相机与Human的max及变化通道数均为0。meal_matched_history.json可直接复核原PNG身份和比较结果。

**定位结论：旧例中的41来自不匹配的reset／渲染历史对照，不需要开启或切换外观也能复现；不应把它直接作为变体串色证据。** 尚未追踪SAPIEN底层为何历史引起盒盖边缘1像素变化，因此不将其包装成已修复的渲染器问题。

诊断性的原生状态回写另有独立记录：正确限定env0后可执行，但产生新的一通道1级差及额外状态变化，不作为通过证据或修复方案；匹配历史结果不依赖此干预。

## Package Long

125109对照相同seed7、noise0、2env、相同4步动作（每维0.01*sin(维度索引+step)）：

|比较|初始物理与控制对照|4步最大差|
|---|---|---|
|新建原生 vs 新建enabled original|全部0|每步0|
|新建原生 vs 新建variant_1|全部0|每步0|
|原生第一段 vs 原生运行4步后reset的第二段|物理状态相同，但drive targets不同，最大0.0099991178|4.0531e-6、1.48147e-4、1.48196e-4、1.47823e-4|
|原生第二段 vs 相同动作历史后variant_1第二段|全部0|每步0|
|原生第二段 vs 相同动作历史后original第二段|全部0|每步0|

**定位结论：上轮把新建原生环境与已运行一段动作、再reset的候选环境比较，控制初态不等价。** 首个观测分歧在机器人get_drive_targets（最大约.01），旧物理state快照没有包含此字段。原生自己也复现上轮那条差异序列；对齐历史后variant_1差异消失。

不能仅凭相关性断言唯一内部原因是drive targets，求解器缓存等历史亦可能参与；本轮未做单独重写drive target的因果干预。也不把原生reset保留目标的行为直接归咎于新增外观。若要修改原生reset政策，应另行讨论其任务语义。

## 下一步最小修正位置

应先修**检查器的对照组织**，而非改外观、几何或放宽阈值：

1. Meal为每次A4/A5比较提供同seed、同次数、同env_idx顺序、同render/readback顺序的关闭外观控制；不能始终拿一张短历史原生图对所有后续场景。
2. Package每个方案独立成对新建原生/候选，或让二者经历完全一致的前置动作和reset历史；比较前先核对物理状态、控制器状态及drive targets。初态不等价时应报告对照无效，而非归类成变体失败。
3. 保留原数值/RGB判据及原始失败记录；用修正后的检查器补齐之前中断的十套用例。最小case消除差异不等于所有候选或完整机器人任务已通过。

## 当前状态

- ScoopTomato A5：已记录重评通过；随机复现未测。
- Meal开盒／长任务：原阻塞已定位为历史不匹配，匹配历史的variant_1诊断通过；正式20例A5尚未补齐，不标整体通过。
- Package Long：新建及匹配历史variant_1的短步诊断通过；正式十套短步仍待用公平对照复验，A4/A5先前通过结论保持。

## 作业与留存

所有作业均Server3 / lyg0295 / G7一个共享shard、--export=NONE，无嵌套srun：125106部署缺目录后FAILED、25秒（尝试停止时已失败）；125107诊断性全批state回写形状错误、FAILED、16秒；125109完整最小矩阵COMPLETED 0:0、44秒；125111两入口匹配历史矩阵COMPLETED 0:0、76秒。合计161 shard-wall-seconds，不是GPU活跃计算秒或整卡费用。无本人在途作业。

原始矩阵report、轨迹、控制器状态、两版实际脚本、源码/图片哈希和收据随档案保留；manifest记录实际依赖及全部部署代码身份。原PNG在/data/home/pb/minimal-diagnosis-20261121/results-125109和results-125111，未删除旧证据。未commit／push，未改生产或验收阈值。
