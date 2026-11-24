# Furniture Assembly 位置变化

覆盖 `LayFlatPanel`、`InsertRail`、`FastenScrew`。三个短任务沿用各自的原生 `make/reset`。显式位置按场景分别选取，用于复现拾取、对槽和转翼的不同接近路径。

## 范围与阶段

表中标称和偏移均为 cm。世界 +X 指向桌内，+Z 向上，俯视逆时针为正偏航。`reset` 请求的 XY 是世界绝对坐标，单位 m。XY 在矩形内连续取值，偏航使用三档显式角度，单位 °。运行值由位置解析器及任务的原生标称值给出。[位置解析器](../../../../tasks/furniture_assembly/position_layout.py)

| 短任务 / 变化 | 标称 | 原生域 | 显式域 | 操作边界 | 图 |
|---|---|---|---|---|---|
| LayFlatPanel · 导向架 XY | (−13, 20) | X ±3、Y ±2.5 | X ±4.5、Y [−1, +4.5] | 架底由桌面支撑。立板跟随导向架，向上越过槽壁。架底须与固定放置区有间隙。 | [导向架 XY](01_rack_xy.png) |
| LayFlatPanel · 导向架朝向 | 0° | ±9° 连续 | −10°、0°、+10° | 同时旋转槽和立板，改变夹取方向。 | [导向架朝向](02_rack_yaw.png) |
| InsertRail · 待拾导轨 XY | (−13, −27) | X ±4.5、Y ±3.5 | X ±6、Y [−5.5, +4] | 改变抓取距离，靠板一侧须留出净距。螺钉跟随导轨。 | [待拾导轨 XY](03_rail_xy.png) |
| InsertRail · 待拾导轨朝向 | 0° | 0° 定点 | −10°、0°、+10° | 改变夹持方向，抓起后需重新朝板槽对准。 | [待拾导轨朝向](04_rail_yaw.png) |
| InsertRail、FastenScrew · 交接板件 XY | (−13, −6) | InsertRail 定点，FastenScrew X ±3、Y ±2.5 | X ±1.5、Y ±1.2 | 交接板件整块落在原生成功区，槽口、止挡、已就位导轨和翼螺钉随板变换。 | [交接板件 XY](05_panel_xy.png) |
| InsertRail、FastenScrew · 交接板件朝向 | 0° | InsertRail 定点，FastenScrew ±9° 连续 | −7°、0°、+7° | 改变插入轴和翼部接近方向，保留放平后可交接的完整板件占地。 | [交接板件朝向](06_panel_yaw.png) |

`LayFlatPanel` 从槽内立板开始。使用 `position_layout` 时，立板中心对齐槽中心，保留原生 Z 和 +90° 立板姿态。抓住高于槽壁的板边，向上取出，转平后放入固定区域。原生判据要求板件正面朝上、全轮廓进入放置区、松手并连续稳定。`InsertRail` 以这一放平姿态开始。

`InsertRail` 从沟槽朝上的固定板和桌面上的自由导轨开始。先提起导轨，再由板局部 −X 槽口沿 +X 送到止挡。原生判据在板件局部坐标下验证位置、朝向、释放和稳定。`FastenScrew` 从原生固定导轨根及其翼螺钉关节开始，导轨就位变换由实测板件姿态决定。接触翼部后从俯视顺时针拧到原生关节目标。测试的短转动门槛为 3°，原生终点为 90°、容差 0.05 rad。

省略 `position_layout` 时，三个短任务保留原生随种子变化的初始化。配置为 `{str(env_idx): {...}}`，每个选中环境须恰好提供一行。每行缺省字段取该短任务标称值，空行用于复现标称初态。未知字段、非有限坐标、不在范围内的坐标、非三档偏航和错误的环境键在 reset 写入前报错。部分 reset 可用项目 SDK 的原生 indexed apply。`FurnitureAssemblyLong` 保持原生单环境阶段流程。Windows CPU 验证相同 seed 下附带 `position_layout` 时，Long 仍按原生逻辑忽略该选项，架、板、轨位姿逐张量一致，阶段为 0。

## 工程验证

主批次在 `f74e6b2d269fdf7ba0e1e8ea82cd6414c9a3d478` 使用 Windows PhysX CUDA 双环境、Sharpa 短任务、SAPIEN `3.0.3+dexarena.gpu1.wininterop5` 和 indexed apply 1。以下是主批次数据。[逐点时序与实测 CSV](runtime_cuda/POINTS.csv) · [原始运行读数](runtime_cuda/results.json) · [本机 SDK 核验与运行回执](runtime_cuda/SDK_AND_PROCESS.json)

| 短任务 | 合法初态 | 越界拒绝 | 仅 reset env0 / env1 | 指尖 IK | 短动作达标 |
|---|---:|---:|---:|---:|---:|
| LayFlatPanel | 13/13 | 2/2 | 7/7、6/6 | 9/13 | 0/2 |
| InsertRail | 23/23 | 4/4 | 12/12、11/11 | 21/23 | 0/2 |
| FastenScrew | 13/13 | 2/2 | 7/7、6/6 | 13/13 | 1/2 |

主批次的 XY 网格使用两轴边界与过标称点的中心线相交，另测三档偏航、同场叠加角点和略超边界的请求。对非对称的导向架及自由导轨，第二批在几何中心和两处真实边中点各另测一行。位姿复核来自 reset 后的真实 Actor 和 articulation link。逐点核对关节零位、阶段字段和固定放置区。两次快照之间不步进物理，通过比较未选环境的物理状态、任务状态和步数的字段摘要验证隔离。越界行比较两个环境。每项另验证 `env_idx=[1,0]` 请求下两个不同朝向正确路由。主批次各标称样点的机器人根位姿、关节 qpos 和 qvel 与同种子原生 reset 相同。

补验提交为 `31091fc17ddc9b658255f90af70758f1a2a6163f`。共享 reset 在该版按家族选择位置解析器，家具三短任务的解析和位姿写入路径相同。使用同一 Windows CUDA SDK 验得六个补充初态与双向 reset 隔离均通过，五个点通过 IK。`LayFlatPanel / RXY-10` 的指尖最大误差为 30.36 mm。合计 55/55 合法初态、8/8 越界拒绝、48/55 指尖 IK。[补验逐点 CSV](runtime_cuda_midpoints/POINTS.csv) · [补验原始读数](runtime_cuda_midpoints/results.json) · [补验 SDK 与回执](runtime_cuda_midpoints/SDK_AND_PROCESS.json)

| 净距与支撑 | 最紧组合或记录 |
|---|---|
| 导向架占地至真实桌边、至固定放置区的 Y 向间隙 | `LayFlatPanel / C-edge`，按实测位姿投影分别为 29.667 mm、4.673 mm。槽内原生落差 1.500 mm。13 个立板释放点均触及槽底或支撑壁，最大位移 1.501 mm、最大转角 0.001°。 |
| 待拾导轨和平板完整投影的 Y 向间隙 | `InsertRail / C-lane` 为 3.556 mm。23 个自由轨释放点均取得桌面支撑，最大位移 0.020 mm、最大转角 0.003°。 |
| 平板完整轮廓至固定放置区边界 | `InsertRail / C-far`、`FastenScrew / C-far` 均为 5.553 mm。已就位轨与板槽每侧余量 2.500 mm，轨根与螺钉子 link 按原生固定关系复核。 |

释放探针使用 8 步机器人静止目标，要求支撑力峰值大于 0.001 N、物体位移不超过 8 mm、转角不超过 5°。图中的完整桌面和机器人底座来自实际碰撞形状投影，物体轮廓来自原生碰撞尺寸。图中文字的几何间隙由真实 reset 的读回位姿计算。单变量样点和叠加样点的间隙分别标示。遥操作需复核手指在运动中的净空。[测图几何](PLOT_GEOMETRY.json) · [制图脚本](../../../../tools/variation/plot_furniture_positions.py)

IK 采用原生拇指、食指跨度及实际关节限位求解，逐项门槛为最大指尖误差 15 mm。立板和待拾导轨检查接近、夹取与上抬，插轨另检查槽口对准。拧翼检查接近、夹取及顺时针初段。立板失败行 `RXY-1`、`RXY-2`、`RXY-3`、`C-edge` 的最大误差为 24.32–32.41 mm。插轨失败行 `LXY-2`、`PXY-7` 的槽口目标误差为 24.68、23.46 mm。碰撞和实际夹取需靠动作探针和遥操作验证。

短动作在标称和 `C-far` 各执行一次。立板两次均触发原生抓取但未越过槽壁。待拾导轨两次均未达原生抓取并上抬 25 mm 的探针门槛。拧翼标称点达到 29.84°，远角未出现接触。CUDA 短动作 1/6。人工遥操作结果待回填。[复现与遥操作交接](RUN_AND_REPLAY.md)

CPU 单环境在 `31091fc17ddc9b658255f90af70758f1a2a6163f` 独立通过 55 个合法点和 8 个越界点，IK 47/55、短动作 2/6。三个任务并用显式位置与 `furniture_appearance` 时，位姿检查和切换至 `variant_3` 的原生外观记录均通过。共 55 项家具单元测试通过，含其他家族使用共享 reset 入口时原样传递其位置请求的契约。[CPU 原始运行](runtime_cpu/results.json) · [外观并用记录](runtime_cpu/appearance_compat.json)
