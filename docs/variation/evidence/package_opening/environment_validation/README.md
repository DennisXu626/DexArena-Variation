# Package 十套正式环境短检（A4/A5＋固定动作）

依据用户提供的 docs/variation/validation/README.md 正文。用户已审核十套外观；本记录区分A4/A5通过和短步动力学未通过，不标整体正式验收通过。

## 结论

|入口|原版＋十套A4|双向A5|随机序列复现|4步同动作对照|
|---|---|---|---|---|
|OpenPackage|11/11|20/20|通过：独立重建两次，各6次reset的双环境实际ID序列一致|11/11通过|
|ExtractApple|11/11|20/20|同上|11/11通过|
|Long|11/11|20/20|同上|original通过，variant_1超过1e-6，其余9套未测|

A4/A5全部通过，共33行A4、60例A5。短步Long不能标通过。完整机器人任务成功轨迹／成功率未测；阶段临界状态、其它手型／规模／seed／噪声／压力、性能与显存未测。

## 范围和判据

Server3 / lyg0295 / G7，Sharpa、2env、PhysX CUDA＋GPU渲染，seed7、robot noise0。完整任务ID、包版本、检查器及catalog字节身份见各identity.json。实测基线HEAD aee41a3，加用户审核的未提交外观快照；source_manifest.json逐文件SHA-256已核对本地，不把HEAD冒作未提交内容身份。

每入口两个独立关闭外观原生环境，保存物理／碰撞／关节参数、初态、初始info和各路RGB，量化native_noise。开启外观的original与原生对照；original＋十套逐个点名，核对实际回合ID、部件颜色、粗糙度、金属度及纹理下载像素。苹果像素期望复用生产recolor_apple，证明配方绑定一致，用户审美已另行通过。

每款切回original，材质各槽及纹理通道身份、状态、初始info和各路RGB对照原生；图中目标变化以各RGB相机（含Human）对齐实体分割统计。A5两环境先不同方案，分别只reset env1与env0恢复original，核对选中行目标RGB与原生局部reset控制、未选行状态／计数／材质／方案记录／随机流及各路整帧RGB。数值阈值1e-6；RGB最多8个通道变化1级。selected全帧差另作诊断，不代替目标区域检查。

原生和候选的完整场景碰撞、质量、惯量、关节限位／摩擦／驱动参数以及对象视觉几何／UV指纹一致；没有改动生产物理、任务门槛或动作逻辑。33行的请求→实际ID、预期配方、原帧名和SHA见各scheme_table.json。各report引用完整signatures.json.gz，所有内容块的规范JSON SHA-256已独立复核。

## 短步失败与原生噪声控制

因为新增苹果亮度参数在外观reset处理器中应用，另行对照同seed、同动作的4步轨迹。动作是每维0.01*sin(维度索引+step)，不是机器人成功策略。短步使用state观测，不做RGB渲染。

Long的variant_1在第一步盒盖角度出现4.0531158447265625e-6的差异；整段最大状态差0.0001481957733631134，位于第3步env1的package_1 articulation状态分量16。奖励、terminated、truncated与原生保持一致。原生两次独立同动作轨迹三入口差值均为0（native_trace_noise.json），因此现有证据不能将候选Long差异归为已测原生随机波动。没有放宽阈值，也未修改生产代码来掩盖差异。

完整原生／候选轨迹和首个失败在short_trace.json.gz，独立原生控制与前次trace文件SHA见native_trace_noise.json。进一步原因待查，不据此直接断言质量、碰撞或材质绑定有错。

## 检查器修正与运行身份

- 123844：OpenPackage完整通过。ExtractApple和Long在新检查器中被误报：env0状态快照错误包含单独命名的env1 plate_1，选中env1正常重置后被当作env0变化。此误报不作为生产环境失败；首次日志和原始服务器输出保留。
- 123846：按仓库既有Package tree_row语义修复检查器，仅重跑ExtractApple、Long；二者A4/A5和随机复现均通过。纯CPU回归证明：单独命名env1 actor和合并机器人env1行均从env0快照排除，但仍保留在env1快照。没有修改生产reset代码。
- inputs/checker-123844.py和checker-123846.py分别冻结实际执行版本，identity中的checker SHA可核对；OpenPackage结果沿用旧检查器版本，不冒称全部入口运行同一文件字节。

## 作业与费用

|作业|用途|状态 / 退出码|分配秒|
|---|---|---|---:|
|123844|三入口初检，开包装通过，另两入口暴露检查器误报|FAILED / 1:0|208|
|123846|取苹果、长任务复验|COMPLETED / 0:0|252|
|123847|三个入口11行同动作短步|FAILED / 1:0|59|
|123849|独立原生短轨迹噪声控制|COMPLETED / 0:0|16|

合计535 shard-wall-seconds。每次一个命名G7共享shard，不等于GPU活跃计算秒或整卡费用。按Meal在前、Package在后执行，全部作业结束后本人squeue为空。使用--export=NONE，无嵌套srun；命令包装与收据留本目录。

## 图像与交接

全部各路前后原帧和日志保留/data/home/pb/package-a4a5-final-20261120/results-123844、/data/home/pb/package-a4a5-r2-20261120/results-123846。image_hashes.json记录每张原PNG；本地图册在本轮visualizations/environment-validation/package，含33张同机位A4原帧及两方向A5原帧样例的点击链接，全部A5原帧留服务器。PR仍需附可访问原图或共享产物链接，个人本机链接不能代替。当前未commit／push／创建PR，Long短步差异待审验。

## 最小诊断更新（2026-11-21）

剩余阻塞已定位到原生/候选的reset、渲染或前置动作历史不匹配；匹配历史后的最小variant_1场景差异为0。详见[三项最小诊断](../minimal_diagnosis/README.md)。原失败JSON保留，正式全量复验尚未补齐，不自动改成全部通过。

## 同历史全量复验更新

七入口A4/A5、随机复现及Package全部33对串行短步已补齐通过，详见[最终全量复验](../paired_revalidation/README.md)。本页旧失败和诊断记录保留；新结论仅覆盖最终报告中的限定配置。
