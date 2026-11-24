# 同历史十套全量复验（2026-11-21）

## 最终结果

|家族 / 入口|A4 original＋十套|双向A5|随机序列复现|同动作4步|
|---|---|---|---|---|
|Meal OpenLunchBox|11/11|20/20|通过|本轮未新增|
|Meal PlaceBread|11/11|20/20|通过|本轮未新增|
|Meal ScoopTomato|11/11|20/20|通过|本轮未新增|
|Meal Long|11/11|20/20|通过|本轮未新增|
|Package OpenPackage|11/11|20/20|通过|11/11|
|Package ExtractApple|11/11|20/20|通过|11/11|
|Package Long|11/11|20/20|通过|11/11|

七入口共77行A4、140例A5全部通过，随机序列均由两个独立环境重建复现。Package三个入口共33对短步轨迹全部通过；每对物理初态、控制器状态及drive targets/velocities差为0，四步机器人/物体状态、奖励、terminated/truncated及info逐值差均为0。各A5选中行与当前匹配历史的原生目标区域RGB差均为0。

这是限定环境短检通过，不是完整机器人策略成功率或所有部署配置的验收批准。

## 修正的检查方式

生产任务、几何、碰撞、物理和外观配方未改。新增check_ten_environment_paired.py：原生控制与候选同步经历每次full reset、env_idx局部reset和同次render/readback。每例保存其当前原生before/after签名及控制图，避免拿短历史原生图对照后续长历史候选。

浮点状态仍用1e-6；选中目标恢复RGB仍最大1级、最多8通道；未选行一般RGB同上。仅Meal舀番茄未选腕部相机使用用户已确认的最大3级、最多8通道和5像素组合规则。没有将RGB上限整体改为41/60，也没有把短步状态阈值改为1e-4。

短步采用check_package_short_trace_paired.py：每个ID独立新建原生实例，完成reset/测量后关闭，再独立新建候选实例，reset后先比对物理/控制初态，再跑相同4步动作。每个实例内部始终num_envs=2，串行化的是两个BaseEnv测试实例，不是取消环境并行。

## 作业、初轮记录与费用

- 125331：Server3 / lyg0295 / G7，共1013秒，最终状态FAILED 1:0。七入口A4/A5及随机复现全部成功；随后首版短步检查同时保留原生/候选CUDA实例，在original对照即出现异常。该初版短步不作为有效变体判据，原始结果保留在package/short_trace_initial.json.gz，实际脚本short_trace_simultaneous.py单列，不覆盖。
- 125378：G7，共223秒，COMPLETED 0:0，严格串行的33对短步全部通过。此结果见package/short_trace.json.gz及对应实际脚本。并未据此宣称已定位SAPIEN多实例异常的底层机制，仅排除这种测试组织方式。
- 生成串行提交包装时曾因空脚本被sbatch拒绝，没有创建额外作业或GPU分配。

合计1236 shard-wall-seconds；一个命名G7共享shard，不是GPU活跃计算秒或整卡费用。命令使用--export=NONE、无嵌套srun，执行脚本和两份原始收据随档案。

## 版本与完整性

基线HEAD aee41a3加用户审核的两家族未提交外观与新检查器；不是虚构已提交版本。family source_manifest.json仅筛选该家族和适用检查器，joint_source_manifest.json保存联合部署来源。各identity记录实际任务ID、backend、seed、num_envs、catalog/检查器SHA和包版本。首次/最终短步脚本SHA与各自report对应，避免把最终脚本冒作旧失败运行代码。

report引用的全部signature块，已解压并独立重算规范JSON SHA-256；77个请求ID及实际ID、140个用例数和随机复现已核对。图册98张原PNG已对服务器image_hashes逐张校验；另有从原图缩小的联系表，不能取代原帧。Package33对原始轨迹和控制初态也已独立逐值比较。

## 产物及边界

各stage含report、identity、完整signatures.json.gz、11行scheme_table和全部原帧SHA。全部相机/原生控制/选中未选前后PNG保留/data/home/pb/paired-full-20261121/results-125331；最终短步在results-125378。个人本地图册位于本轮visualizations/paired-full-gallery/paired_revalidation，含A4原PNG及A5原生/候选样例链接。正式PR需附可访问原帧或共享产物链接，不能只依赖个人路径。

限定Sharpa、2env、PhysX CUDA＋GPU渲染、seed7、noise0、程序午餐盒、显式全部ID和初态附近双向reset。随机检查为两个重建各6次reset序列复现，不宣称遍历全部随机轨迹。完整机器人任务成功率、成功临界阶段隔离、其它手型/规模/噪声、性能/显存和长期压力未测。旧失败、原生校准和最小诊断均保留，新结果只替代对应限定检查结论。未commit/push/创建PR。
