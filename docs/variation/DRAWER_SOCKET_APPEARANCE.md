# Drawer / Socket 外观：CPU准备与短检提案

基线main `793c74798c3291155e7010a0688053c1fbe57faa`。**GPU0，没有任务加载、渲染或作业提交；运行及真实感尚未验收。**

## 最新 · 仅返工抽屉（等待运行授权）

抽屉前版视觉不通过，插座沿用 [作业 121640](evidence/drawer_socket/runtime_002/README.md) 的已验收结果。方案 ID 保持 `original`／`warm_white`（A · 浅橡木与暖白）／`neutral_grey`（B · 浅灰与石墨色）；[分件材料与产品链接](../../assets/appearance/objects/drawer_plug/drawer/README.md)。此节覆盖下文中的抽屉旧方案与旧预算，历史报告保留。

- 新增 `--drawer-review`，只覆盖 OpenDrawer 和 PickCharger 各 2 环境，先做原生可重复对照，然后两任务各采 original、A、B。OpenDrawer 使用原生关闭 `0 m`，PickCharger 使用原生中抽开度 `0.22 m` 与原生 Charger。各任务的独立检查器相机配置在构建前固定：观察闭合时的全柜与台面和偏高前侧打开时的内箱。只改取证相机配置，场景、灯光、任务 reset、物理均原样。
- 每组使用 env0、seed 7、1280×960、默认曝光，同 seed 完整状态和关节开度有断言；保持原图像素，并按组固定裁剪框。闭合检查全台面、侧板、三层把手；开屉检查外抽面、把手、内侧壁与底板。纯几何投影只验证构图范围，实际图像和遮挡待审。
- 拍齐六帧后用同一作业继续关闭/原版、物理初态、候选恢复、复现、局部隔离检查。预计 17 次构建（含一次额外原生对照），无物理步进，PickCharger 全程保留原 Charger，不重复插座或 Long。
- **申请，不是批准**：总墙钟 60 分钟、单卡最多 240 分配秒（4 分钟调度）、应用 205 秒、只提交一次，排队最多 120 秒，最迟第 39 分钟提交且至少余 21 分钟，第 45 分钟进入至少 15 分钟收尾。只在新授权、刷新占用和通过只读预检后提交。
- 续用 Ceph `/mnt/ceph2/xkl/DexArena/drawer_socket_appearance_20261117/runtime_003/`，预估新增 80–140 MiB 输出、一个约 85 MiB 的独立源码树及少量缓存；提交前度量整根历史留存和实际余量。用途与监控同上轮：整根 768 MiB 约每秒采样停止（非硬封顶）、日志 8 MiB、单文件 64 MiB、禁 core、共享资产只读、服务器最低余量 20 GiB、本机 D 盘 10 GiB。派生缓存与临时产物隔离，无自动重排、重试或扩大存储。D 盘日志 `D:/Logs/DexArena/drawer_socket_appearance/runtime_003/`。
- [检查器](../../tools/variation/check_drawer_socket.py)入口为 `--drawer-review --approval <本轮批准记录> --output <私有子目录>/output`；具体验证脚本和包装需在提交前冻结并检查。CPU 准备不创建批准记录，不访问 GPU。

## 历史 · 材料与唯一参数源（v1）

[运行catalog](../../tasks/assets/variation/drawer_plug/fixtures_v1/catalog.json)仅维护一份；对象档案只引用。[真实产品、工艺、许可与RoboDojo参考](../../assets/appearance/objects/drawer_plug/drawer/REFERENCES.md)；[平面设计色板](../../assets/appearance/objects/drawer_plug/drawer/material_board.png)不是任务图。

| ID | 全部抽屉板面 | 插座壳体 | 细节 |
|---|---|---|---|
| original | 原参数与原色图像素 | 原银色金属渲染 | 原版 |
| warm_white | 暖白丙烯酸涂装，适度哑光 | 暖白哑光PC | 把手、滑轨、孔内衬原版 |
| neutral_grey | 浅灰哑光层压覆面 | 炭黑细哑光PC | 把手、滑轨、孔内衬原版 |

参数为渲染设计估计，不是厂商测量值或精确复刻。没有新增法线/粗糙度贴图、UV、几何或外部纹理。候选替换板面木纹颜色，不给木纹染色后改叫塑料。原板材map_Kd之外的通道若出现则报错待复核。

## 配置与默认

[关闭](../../examples/variation/drawer_plug/fixtures/default.json)、[original](../../examples/variation/drawer_plug/fixtures/original.json)、[逐环境固定](../../examples/variation/drawer_plug/fixtures/fixed.json)、[随机](../../examples/variation/drawer_plug/fixtures/random.json)、[Charger联合](../../examples/variation/drawer_plug/fixtures/combined.json)均可作为gym.make kwargs展开（仅在另获批准后运行）：

```python
kwargs = json.load(open("examples/variation/drawer_plug/fixtures/combined.json"))
env = gym.make("DrawerPlugInsertPlug-Sharpa-v1", num_envs=2, **kwargs)
env.reset(options={"env_idx": torch.tensor([1], device=env.unwrapped.device),
    "drawer_plug_appearance": {"scheme_id": "warm_white"}})
records = env.unwrapped._fixture_appearance.records
```

字段：enabled、mode=explicit/random_choice、scheme_id/scheme_ids、seed、per_env（字符串env索引）。reset普通请求覆盖构建per_env，reset per_env优先级最高。enabled是构建期开关，不能在reset临时安装适配器。默认省略/false不创建适配器、不绑定纹理、不抽外观随机数；original是启用后的原版恢复路径，有材质隔离成本。

每环境独立(seed,env_idx)外观RNG，仅选中reset抽样；记录catalog_version、scheme_id、env_idx、episode_index、实际加载objects。渲染不重选，回合内固定；同seed、环境数、reset顺序可复现。原机器人/位姿torch随机流未改变，不承诺跨环境数/顺序或原任务未有的逐环境原生RNG隔离。

## 实际覆盖和修改

| 任务（均为DrawerPlug…-Sharpa-v1） | Drawer | Socket | Charger |
|---|---|---|---|
| OpenDrawer | 47网格/32板件/15硬件 | N/A | N/A |
| PickCharger | 同上 | N/A | 原适配器与catalog |
| InsertPlug | N/A | 6壳+2暗孔内衬 | 原适配器与catalog |
| Long | 同上 | 同上 | 原适配器复用；新增入口放行/结束钩子，待工程检查 |

新[适配器](../../tasks/drawer_plug/fixture_appearance.py)只操作渲染参数/私有纹理。四任务在原生reset末尾调用；Socket使用原Charger的builder复制函数。Charger适配器及catalog逐字节不变。Long以前拒绝Charger配置，本次只放行白名单并调用原finish_reset，不改三部件参数，不冒充历史Long验收。

抽屉按URDF语义/OBJ名绑定，未知网格报错。原图只读；首次渲染前建立环境私有稳定纹理，reset上传原像素或候选常量像素，维持UV/alpha/纹理身份。把手/滑轨不替换色图，物理builder不变。所有成功/奖励、机器人、位置/几何/物理代码在剥除明确列出的渲染钩子后与基线AST一致。

## CPU预检

```bash
python -B tools/variation/check_drawer_socket.py --static --asset-root /authorized/drawer
python -B tools/variation/check_charger_a4_a5.py --static
python -B tools/variation/check_static.py
python -B tools/variation/check_appearance_archive.py
git diff --check
```

原Charger静态断言只增加上述钩子的精确归一化，不整体放宽受保护方法。新检查完整AST/JSON/源文件hash/像素色域与alpha；不导入tasks/torch/SAPIEN。源闭包96文件99,044字节已在本机只读核对。省略asset-root只能报告代码检查，不能宣称资产已查。

运行环境按[SETUP](SETUP.md)既有Python3.10/Torch2.6/SAPIEN3.0.3/ManiSkill3.0.0b22复用，本轮未刷新服务器状态。源抽屉目录没有CoACD派生缓存；未来提交前须核对安装加载器是否需要生成、缓存身份和本线私有写盘路径。不能写回共享资产；不以先加载一次代替预检。未开始部署或服务器调查。

## 一次短检提案（非授权）

- 总墙钟75分钟，单卡≤600分配秒，应用540秒，最多一次提交，无重试。排队≤120秒；最迟第48分钟提交且余时≥27分钟；第60分钟开始最后15分钟收尾。
- 32次环境构建：每任务native/disabled/3方案5次，联合Charger1次，随机复现2次，四任务合计32次。短任务各2env，Long1env。其余恢复和阶段检查用原实例reset；预算不足或任何关键断言失败即保存部分结果停止。
- 已准备[运行脚本](../../tools/variation/check_drawer_socket.py)：`python -B tools/variation/check_drawer_socket.py --approval <explicit_receipt.json> --output <approved_root>/run_001`。receipt需approved、blockers_resolved、scope=drawer_socket_shortcheck、frozen_head、storage_root，并要求Slurm分配。当前不生成批准文件或提交命令。
- 覆盖绑定/参数/贴图、关闭与original、同seed物理/初态、候选→original恢复、固定/随机/回合记录、两次env1局部reset、env0状态/target/材质/纹理/外观随机流/记录/全相机RGB隔离，env1必须发生RGB变化。Charger原方案联合核对；Long原生task_phase仅工程reset，不进行机器人动作。
- 原任务初始化使用全局torch随机流。需比较外观关闭和启用在同reset序列下的原生随机消耗；不能把env1正常reset推进全局RNG说成新外观污染，也不改原位置采样机制。

| 产物 | 实际拟路径 | 增长与控制 |
|---|---|---|
| 本机日志/传输临时 | `D:/Logs/DexArena/drawer_socket_appearance/runtime_001/` | 回传估计≤200MiB，D最低10GiB，不回退C |
| 私有源码/小资产闭包/缓存/输出 | `<approved_private_ceph_root>/drawer_socket_appearance_20261117/` | 新Ceph专用根待确认。复用依赖/机器人只读；输出估计100–200MiB，正常峰值估计600MiB，非实测保证 |
| 根目录合计 | 同上，包含缓存及历史产物 | 768MiB约每秒采样停止，可能越限，最大越限未证明；非硬配额；底层空间最低20GiB |
| 日志/文件/进程 | 同根，HOME/TMP/驱动缓存仅本线私有或只读边界 | 日志8MiB、普通单文件64MiB、禁core；540秒应用/600秒作业；原PGID TERM/KILL与外层保护，无自动重排 |

只需新增确认：本轮一次作业/600秒/75分钟窗口，以及新Drawer Ceph根和其无硬配额采样越限风险。既有保护算法不另建、不重复申请；旧Cabinet路径授权不自动涵盖新根。此前披露的跨PGID后代及全部驱动写盘未证明边界保留。实际闭包/挂载/余量/队列/缓存身份在提交前刷新；出现新固定写盘或容量风险先停。

## 人工真实感清单（待执行）

1. 同seed/初态/相机/光照并排original与两候选；保存全景及从同一RGB裁出的近景，不将裁图冒充新相机视角。
2. 抽屉外侧/可见内侧/封边/开合边界与三层面板一致；涂装和层压板没有不合理木纹，保留金属把手/滑轨，不能整柜同材质。
3. Socket壳体像哑光PC而非镜面金属；孔深、暗内衬、边缘及Charger组合清晰；炭黑不能暗到无法辨孔。
4. 对照产品材料，检查过强高光、拉伸、接缝和纹理噪声；参考约束材质，不要求形状复刻品牌产品。
5. 参数正确、视觉变化、隔离正确、人工真实感分别记录。完整任务成功、训练、A6、大规模、Long双环境不在结论内。
