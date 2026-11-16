# Cabinet剩余对象：准备完成，运行待验证

本轮只增加cabinet、bowl、beads的标量外观参数和原适配器接入，不使用GPU、不加载任务、不渲染。基线main见本PR提交父级；对象仍pending_adaptation，原已验收对象数量不变。没有新的运行通过结论。

## 参数与任务

唯一参数源仍为[Cabinet catalog](../../tasks/assets/variation/cabinet_pouring/v1/catalog.json)，版本cabinet-appearance-v1.1。同一方案控制瓶/盖与实际加载的三个对象，不新增逐对象混配接口。

| 方案 | 柜体 | 碗 | 珠子 | 瓶/盖 |
|---|---|---|---|---|
| original | 恢复原纹理/材质 | 恢复原纹理/材质 | 原蓝色 | 原行为 |
| ocean | 蓝绿调不透明纹理表面，细节保留 | 原纹理暖白调 | 橙色 | 既有Ocean完全保留 |
| citrus | 暖木调不透明纹理表面，细节保留 | 原纹理深绿调 | 紫色 | 既有Citrus完全保留 |
| violet | 原版 | 原版 | 原版 | 既有Violet完全保留 |

所有新参数alpha=1，写入时仍保留原alpha；不改transmission/visibility。柜体不透明纹理面以外的把手、操作件和透明部件保持原版；碗内外/边缘共享原单材质，保留原纹理与几何，不能声称增加了独立内外材质槽。珠子默认16颗/4mm，数量可用原任务参数配置，其生成、碰撞、质量及阶段关系均不改。无新增贴图、UV、模型或原资产副本。

| Sharpa任务 | cabinet | bowl | beads | 运行状态 |
|---|---|---|---|---|
| OpenCabinet | 加载 | 不适用 | 不适用 | 待验证 |
| PickBottle | 加载 | 不适用 | 加载 | 新对象待验证；保留既有瓶/盖及位姿验收历史 |
| UnscrewCap | 不适用 | 不适用 | 加载 | 新对象待验证；保留既有瓶/盖及位姿验收历史 |
| PourBeads | 不适用 | 加载 | 加载 | 待验证 |
| Long | 加载 | 加载 | 加载 | 入口准备，不代表Long运行或全阶段通过 |

完整ID为CabinetPouring<表中名称>-Sharpa-v1。实际映射见[柜体](../../assets/appearance/objects/cabinet_pouring/cabinet/bindings.json)、[碗](../../assets/appearance/objects/cabinet_pouring/bowl/bindings.json)、[珠子](../../assets/appearance/objects/cabinet_pouring/beads/bindings.json)。柜体缓存静态资产含base无视觉、link_0门及操作部件、link_1柜身；对实际render parts按保留纹理/opacity/transmission规则绑定，运行part数仍须核对。

## 最小接入

[既有固定/双环境示例](../../examples/variation/cabinet_pouring/appearance.json)与[随机示例](../../examples/variation/cabinet_pouring/appearance_random.json)原样可用于本轮；禁用initial_pose时可换上述任务ID。**initial_pose仍仅允许PickBottle/UnscrewCap**，范围/采样不扩展。开关关闭不绑定材料、不抽外观随机数，原任务初始化路径保留。

adapter收集实际存在的瓶/盖表示、各柜体link、target及particles；不制造缺失对象。原生文件加载材质按既有方式构建，并保留跨env共享owner拒绝检查；珠子显式材质只在启用外观时分env调用相同build_sphere helper，再Actor.merge回原逻辑粒子。半径/颜色/动态类型/初态参数及后续物理配置保持。共享几何不等于共享可变材质，运行隔离必须另测。

每次仅对env_idx选中项恢复捕获的base_color/base_color_texture/roughness/metallic，再应用方案；未覆盖的violet新对象恢复原版。新功能从不改变其它材质字段，故切original不遗留新参数。所有阶段表示使用同一回合选择，无阶段重抽。记录沿用appearance scheme ID；无瓶任务pose为null，无盖任务不伪造cap位置，原两试点的字段值保持原行为。manifest一次记录新catalog版本/代码/资产身份，不在每回合重新哈希。

OpenCabinet、PourBeads和Long原reset末尾增加与既有子任务同样的finish_reset钩子。父类有接入不代表子任务、其它手型或Long已经运行验证；奖励、成功、机器人、几何、物理以及位置解析均未修改。

## 静态复核与来源

运行CPU静态命令（不导入tasks）：

```bash
python -B tools/variation/check_static.py
python -B tools/variation/check_appearance_archive.py
git diff --check
```

三个对象档案记录缓存资产revision、visual/材质槽/UV和源文件哈希；不是运行资产已匹配的证明。参数为项目自制，随仓库许可；原PartNet/RoboCasa资源按[原资产说明](../../tasks/assets/README.md)获取，未新增第三方图片。没有素材生成脚本需要运行；catalog内六组标量就是方案定义。不得用历史模型图或瓶/盖实景冒充本轮预览。

## 下一轮集中短检提案（尚未批准，不执行）

申请非GPU全程墙钟最多60分钟、单卡累计最多600分配秒、一次作业、应用540秒。历史GPU额度不沿用。先留15分钟提交准备、最多10分钟分配、最后至少15分钟收尾；第35分钟仍未提交则停，第45分钟进入收尾，失败不重试。以下只是预算估计，不是测量或授权。

四个短任务各2env、Long先1env，不做机器人动作或完整任务成功。逐任务先关闭与显式original同seed基线，再ocean/citrus同光照/原相机对照；读全部实际parts/material/texture，核对原数量、几何、质量/惯量/摩擦、关节、初态和成功代码；从候选切回original逐属性/贴图与基线比较。violet对新对象必须回到native、瓶盖仍保持旧violet。

四短任务逐个做不同方案2env、两次仅env1 reset，期间不推进物理，验证env0状态/目标/材料/贴图/记录/外观和位姿RNG状态及原RGB观测/human像素不变。相同种子/配置/reset顺序重复随机选择序列；检查回合内固定和记录一致。珠子全部颗粒及柜体所有link都需覆盖，非加载对象标不适用。Long仅工程检查其原生表示切换后外观持续，标注工程触发，不代表机器人长任务或A6；遇原任务单环境限制不绕开。

PickBottle/UnscrewCap做最小旧瓶/盖A/B/C和附着/自由盖工程切换检查；既有位姿关闭及xy_v2原合法固定点联合对照，局部reset未选位置/RNG不变，不扩大范围、不改变成功门槛。优先复用已有M2/续篇脚本、原生相机与环境；若现有运行接口遇到核心/物理/语义阻断则停止并交回，不改库绕过。

拟本机输出D:/Logs/DexArena/cabinet_remaining_appearance/和本轮D盘交付目录；拟服务器专用根/mnt/ceph2/xkl/DexArena/cabinet_remaining_appearance_20261116/（Ceph不是WindowsD盘，待Dennis明确确认），资产/依赖只读，必要小型派生缓存在该根。不开跑前不创建服务器副本。预计RGB/状态/manifest合计100–200MiB、连源码/缓存正常峰值估计600MiB，须CPU预检实际闭包大小后确认。

提议沿用受监测模式：总目录768MiB约1秒采样触发停止（可延迟越限，非绝对硬封顶）、日志8MiB、普通单文件64MiB，服务器底层最低20GiB/本机D盘10GiB；保留已测试PGID清理和调度硬时限。只清理本线进程，不影响其它健康作业；未知固定驱动写盘/跨PGID后代边界先列明，不能把模式或预算当已批准。依赖/路径/身份、Monica与队列刷新通过后才可提交；任何绑定/物理/渲染/隔离断言失败即保存有限证据并停，不再提交。

本轮停止于草稿PR交接，真实图、运行材质/恢复、局部reset、阶段一致性与预算保护均待Dennis批准下一轮后核定。

## 运行准备续篇：预算已批，存储风险尚未确认

本轮已获总墙钟60分钟、一次单卡600分配秒/应用540秒预算；没有查到本线Ceph路径及无硬配额风险的明确确认，因此**没有上传、创建服务器目录、生成缓存、加载仿真或提交GPU作业**。旧Mouse目录风险批准不代替本线确认。原短检提案保留，预算批准与存储风险批准分开。

[专用短检脚本](../../tools/variation/check_cabinet_remaining.py)已完成CPU静态准备：[状态/未运行矩阵](evidence/cabinet_remaining/runtime_preflight_001.json)。`--static`不导入仿真；实际运行在导入tasks之前必须检查独立approval的storage_risk_confirmed_by_Dennis、accept_sampled_limit_overshoot和blockers_resolved。预算已批但风险未确认的负例被拒绝，未创建输出。此负例/静态通过不是材质、RGB、物理或A4/A5通过。

脚本按四短任务2env、Long1env，先原生/关闭，再original/ocean/citrus/violet及切回原版；核对实际parts/material/texture、物理指纹/索引/初态/drive targets、固定/随机/记录、两轮env1局部reset的env0状态/随机流/材质/贴图/记录和原RGB/human，最后做原瓶盖工程切换及已有xy_v2合法点。Long遵循正式注册的原生参数（注册项含bottle_stage_twins=True，不以构造函数默认False推断实际注册模式），不强改表示机制；工程触发不代表机器人执行。任一关键断言失败即保存有限部分结果、停止，不自动重试。完整矩阵仍全部未运行。

只读检查拟根realpath仍为`/mnt/ceph2/xkl/DexArena/cabinet_remaining_appearance_20261116/`，目录尚不存在，父目录为本用户所有，实际Ceph挂载底层余量超过20GiB；Cabinet源资产627文件/1321905字节，选定URDF/模型已定位。主要包元数据沿用旧基准；不是本线加载验证。完整资产/派生缓存hash与只读兼容、薄入口部署、驱动写盘和新鲜调度状态仍是提交前门槛。

容量估计/边界仍按上方提案：正常峰值估计600MiB、输出100–200MiB，768MiB约1秒采样停止可能越限，非硬配额；日志8MiB、普通文件64MiB、服务器最低20GiB/本机D盘10GiB。旧PGID清理/有界日志核心函数AST核对未变，已有Linux CPU证据，但旧CLI硬编码Mouse，不能直接当Cabinet已部署保护。请Dennis明确接受本线Ceph落盘与上述无硬封顶风险后，再进行受限部署、缓存/保护核对；不将当前就绪资料写成blockers_resolved=true。

排队提议上限120秒；提交时至少留120+600+900=1620秒，所以本轮第33分钟为更严格提交边界（用户第35分钟是绝对上限），第45分钟必须收尾。调度deadline与独立PENDING截止取消须一起落实，`--time`或SSH超时不能代替队列截止。确认未到则完成本地准备后停止，不反复等待、不延长本轮窗口。真实同条件任务图与运行结果仍待批准后补齐，未更改对象验收状态。
