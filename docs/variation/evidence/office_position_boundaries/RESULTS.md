# Office Desk 原生位置检查

工作基线为 `128526c9588098c940b6664372eca8b8eb52aab9`。位置功能采集提交及文件哈希记录在各次运行的 `results.json`。六张图以 Windows 单环境 PhysX CPU 的 reset 读数和本次加载的碰撞部件生成。模型、机器人资源、任务源码和后端同样随原始结果留档。复现顺序见 [RUN_AND_REPLAY.md](RUN_AND_REPLAY.md)。

## 真实初态、固定根支撑与粗略可达性

| 短任务 | CPU 合法初态 | CPU 越界拒绝 | CPU 固定根支撑 | CPU 指尖 IK | 最小完整占地桌边余量（CPU） |
|---|---:|---:|---:|---:|---|
| OpenLaptop | 19/19 | 3/3 | 9/9 | 19/19 | 148.41 mm，C-++ |
| TypeKeys | 20/20 | 3/3 | 9/9 | 20/20 | 5.90 mm，C-++ |
| ClickMouse | 19/19 | 3/3 | 9/9 | 8/19 | 203.38 mm，XY-1+0 |

候选同时覆盖标称、矩形角点和边中点、相对 yaw 三档及八个 XY 角点叠加最大转角的组合。键盘另外实测非对称范围的中心 M。负样点相对 X 下限、Y 上限各越界 0.1 mm，另有不受支持的角度。合法初态与同 seed 的原生关节、速度、机器人姿态、阶段和本体离桌间隙逐项核对。

初筛在键盘 X −2 cm 与极端转角叠加时实际测得壳体越过物理近桌边 3.70 mm。候选 X 下限据此改为 −1 cm，最终最紧组合重新测量为上表所示。三件设备使用原生固定根，标称离桌间隙分别为 4、2、1 mm。八步原生仿真记录根位移、倾角、间隙和接触力。键盘同时比较运动键与 P 目标提示的实际位置。

指尖 IK 使用当前关节的世界轴和限位，求指定指尖或指腹到接近、触碰及短动作途经点的位置误差。门槛为每个目标所有途经点均 ≤15 mm。TypeKeys 同时测五个键。ClickMouse 的未过点均卡在接近途经点，两个后端的标称 N 分别测得约 21.0 mm 接近误差和约 1.5 mm 接触点误差。组合 C+-- 的接近误差为 CPU 33.8 mm 和 CUDA 33.5 mm。已从 CPU 逐点表重新独立构建 N 和 C+--，两点实测根位姿与原记录精确相等，双按钮初态均释放。其他点的误差及关节解见原始结果。

| CPU 逐点数据 | 原始运行记录 |
|---|---|
| [OpenLaptop](cpu/OpenLaptop/POINTS.csv) | [results.json](cpu/OpenLaptop/results.json) |
| [TypeKeys](cpu/TypeKeys/POINTS.csv) | [results.json](cpu/TypeKeys/results.json) |
| [ClickMouse](cpu/ClickMouse/POINTS.csv) | [results.json](cpu/ClickMouse/results.json) |

## CUDA 双环境与局部 reset

Windows 原生 CUDA 使用 SAPIEN `3.0.3+dexarena.gpu1.wininterop5` 和 indexed GPU apply 1。各任务分别只 reset env0 和只 reset env1，两次快照之间未推进物理。选中环境按组合请求读回 XY／yaw，未选环境的物理、关节目标、任务阶段、控制器和任务 RNG 前后相等。TypeKeys 同时记录未选提示的精确位姿与选中 P 键提示读回。

| 短任务 | 合法初态 | 越界拒绝 | 固定根支撑 | 指尖 IK | 局部隔离 | 运行证据 |
|---|---:|---:|---:|---:|---:|---|
| OpenLaptop | 19/19 | 3/3 | 9/9 | 19/19 | 2/2 | [逐点表](cuda/OpenLaptop/POINTS.csv) · [运行](cuda/OpenLaptop/results.json) · [SDK](cuda/OpenLaptop/SDK.json) |
| TypeKeys | 20/20 | 3/3 | 9/9 | 20/20 | 2/2 | [逐点表](cuda/TypeKeys/POINTS.csv) · [运行](cuda/TypeKeys/results.json) · [SDK](cuda/TypeKeys/SDK.json) |
| ClickMouse | 19/19 | 3/3 | 9/9 | 9/19 | 2/2 | [逐点表](cuda/ClickMouse/POINTS.csv) · [运行](cuda/ClickMouse/results.json) · [SDK](cuda/ClickMouse/SDK.json) |

[TypeKeys 首次 CUDA 记录](cuda/TypeKeys_FIRST_CHECK.json) 中，两向隔离唯一差异为未选键帽提示。原生 reset 在调用 `evaluate` 前重开全场 mask，提示更新据此覆盖了未选环境。修复后提示使用当前局部 reset 的选中范围。复跑采集前先将非零阶段夹具的提示写入 PhysX 再读回。两向隔离均通过，选中 P 键提示位置误差均为 0。OpenLaptop 采用首次采集，后续修订集中在 TypeKeys 的提示和隔离夹具。

## 短动作与遥操作交接

每项用原生 `pd_joint_pos` 控制器实际运行标称和困难点，各 96 步，初态后按 IK 关节目标插值。OpenLaptop 检查可观测屏幕接触且开度增加至少 5°。TypeKeys 检查第一个按压释放循环推进至 A。ClickMouse 检查原生有效左键点击。CPU、CUDA 各六次均未达到门槛。OpenLaptop 的 N 从 44.05° 峰值到 CPU 53.58°、CUDA 51.72°，均未测到指定指尖与屏幕接触。TypeKeys 四次峰值按压比例约 0.013。ClickMouse 的 N 和 C+-- 两个后端左键峰值均低于 0.075，指定指腹无可测左键接触。

| 任务 | 标称、组合点 | 遥操作动作 |
|---|---|---|
| OpenLaptop | N、C+--，seed 517，CPU env0 | 手沿半开屏接触边进入后向上带动，观察开始接触、屏轴运动和最终稳住开度。 |
| TypeKeys | N、C-++，seed 617，CPU env0 | 先操作 P 的按住与释放，再尝试 A 和 Enter，并检查最靠边的壳角手部净空。 |
| ClickMouse | N、C+--，seed 717，CPU 均 env0，CUDA 分别 env0、env1 | 试从前上方和壳侧靠近左键，压下时观察是否碰到右键，记录最先受阻的姿态。 |

手动遥操作尚待执行。Long 复查原生入口，Windows CPU seed 817 读回阶段 0 且三件设备同时在场。ClickMouse 另用同一个显式位置依次应用 `navy_satin` 和 `original`，原生两次位姿精确相等，外观历史分别记录两个方案，CoACD 原缓存前后身份一致。23 项既有 Office 合约、当前 Office 外观资产与源码范围检查以及全仓静态检查通过。历史 Mouse 专项静态工具使用早期源码基准，在本轮起始 main 也会报 AST 不同。鼠标物理、材质绑定和布局接口的验证使用上面的当前源码范围与真实运行。
