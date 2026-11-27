# Furniture Assembly 操作路径位置采样

适用 `FurnitureAssemblyLayFlatPanel-Sharpa-v1`、`FurnitureAssemblyInsertRail-Sharpa-v1` 和 `FurnitureAssemblyFastenScrew-Sharpa-v1`。从原 PR #42 的 `338ae6f` 开发，运行依赖均在这份家具改动及其原始基线内。默认构造、原显式 `position_layout` 和 Furniture Long 仍可照既有方式使用。[原范围、坐标与复现](../furniture_position_boundaries/README.md)

## 调用与回放

```python
import gymnasium as gym
import tasks

env = gym.make("FurnitureAssemblyInsertRail-Sharpa-v1",
               position_workspace=True, control_mode="pd_joint_pos")
env.reset(seed=701)
env.reset()  # 同一位置序列的下一次抽样
env.reset(options={"workspace_placement": {"0": "near"}})
env.reset(options={"workspace_placement": {"0": "far"}})
s = env.unwrapped.workspace_records[0]
env.reset(options={"workspace_placement": {"0": s["layout"]}})
```

`workspace_records` 给出实际选中环境最近一次新布局请求、表版本、位置种子、序列号和模式。严格复现机器人起姿及短动作还要使用逐点表的 seed、后端及完整 reset 顺序：先全量 reset 指定 seed，再按该行 options 执行 reset。GPU 局部请求将 CSV 中的 `env_idx` 转为同设备的整数张量。数值请求按各任务完整给出绝对世界 XY（m）和绝对 yaw（°）。近／远预设固定其余坐标。旧显式请求和快照走原路径，固定布局不抽位置随机数。新增随机模式只推进被选环境的独立计数。拒绝未知预设、非法及重复索引、缺字段、无支持的角度、有效格间的空隙、互斥选项和越界值。

## 逐任务范围与操作差异

| 任务 | 怎么抽样 | 同朝向近／远预设在 CPU 的实测差异 | 边界图 |
|---|---|---|---|
| LayFlatPanel | 抽导向架朝向及架根 XY。立板随架。左手从可夹边接近、越壁、向固定放置区搬运，在区上方翻平并准备释放。 | 板边抓取点沿世界 X 相距 13.2 cm，Y 相同。 | [架 XY](figures/LayFlatPanel-rack-xy.png) · [架朝向](figures/LayFlatPanel-rack-yaw.png) |
| InsertRail | 联合抽板根、板角、自由轨相对板的 XY 和世界朝向。右手提轨、调向、对准板局部 −X 入口，沿 +X 推至止挡；自由轨与板仍按各自原生表示放置。 | 固定同一板位和角度，近／远导轨抓取点沿世界 Y 相距 16.2 cm。 | [板 XY](figures/InsertRail-panel-xy.png) · [板朝向](figures/InsertRail-panel-yaw.png) · [轨 XY](figures/InsertRail-rail-xy.png) · [轨朝向](figures/InsertRail-rail-yaw.png) |
| FastenScrew | 按放平交接板的位姿带动已就位导轨和翼头。使用实际转轴跟随顺时针 90° 的分段路径，末端留出退出空间。 | 翼部操作点沿世界 X 相距 4.8 cm，Y 相同。 | [板 XY](figures/FastenScrew-panel-xy.png) · [板朝向](figures/FastenScrew-panel-yaw.png) |

LayFlatPanel 和 FastenScrew 的 `near` 更靠近机器人所在的世界 −X 侧；InsertRail 的 `near` 缩短从导轨到板槽的搬运距离。枢轴、手型、原生成功区和原生阶段状态按任务定义。格在同一朝向或角度组合内等体积，随机先等概率选角度层，再等概率选有效格，在格内连续均匀取值。联合格之间留有空隙，能够实测的边界、面积和采样概率均以实际单元并集为准。[运行表](../../../../tasks/furniture_assembly/position_workspace.json)

## 离线方法与适用边界

从原生 CPU reset 读桌面碰撞面、七臂关节的轴与限位、两指位置、手腕与掌部网格。按板、架、轨的完整轮廓及交接关系检查每格各个角点。对固定朝向，角点覆盖平移引起的极端支撑与轴向分离余量。对候选中心按相邻动作姿态解带关节限位的 IK，两指加腕部第三点约束抓持方向；可试多种进手倾角。按实际关节插值抽查腕部碰撞包络与桌面、架或板的间隙。对单物体，格内目标位移由半对角线界定；对联合格，取主件和从件两个位移上界之和。相同已解姿态在格内的目标误差上界为中心误差加该位移量。

这项筛选覆盖理想持物几何、离散途经姿态、腕掌若干部件的包络和初始支承。指腹变形、失抓、全臂连续碰撞和真实按压／旋拧结果由物理探针与遥操分别记录。LayFlatPanel 在放置区上方检查翻平和准备释放，实际落稳使用原生判据。FastenScrew 的离线见证是能保持同一侧接触方向的分段路线，需换面的布局留作额外试用。窗口边缘和单元间空隙都可因有限搜索形成。[生成器](../../../../tools/variation/build_furniture_workspace.py) · [按层筛选计数及逐格余量](screen.json)

| 任务 | 候选格 | 满足初态几何 | 满足路径筛选 |
|---|---:|---:|---:|
| LayFlatPanel | 288 | 264 | 261 |
| InsertRail | 11,025 | 5,503 | 5,459 |
| FastenScrew | 147 | 79 | 79 |

## 遥操前工程测量

Windows 原生 CPU 单环境逐任务各进行了 8,192 次抽样重播，并对比原生随机、旧显式域参考均匀采样和新位置分布，各用相同八个种子记录真实操作点及 reset 耗时。局部接触与抬升／短转探针使用原生 `pd_joint_pos`。新回合零步读数忽略上一回合残留的 PhysX 接触力，回合开始后的实际接触与原生阶段判定照常计算。默认路径另以 7、47、269 对照原主线状态字节摘要。[CPU 逐点表](cpu/POINTS.csv) · [CPU 汇总与对照](cpu/results.json) · [原生状态及原子拒绝](cpu/native_compatibility.json)

三个后端分别通过 135 个合法初态与 31 个原子拒绝。CPU、Linux 受测提交为 `ecafc5c`，Windows 双环境为 `60f82fa`，三者使用相同任务代码、运行表和主检查器。两套 GPU 各测了 135 次定点局部 reset，逐次核对另一环境的场景、控制器和随机流，三项任务均复现原有乱序显式行与快照行语义。操作点最大读回误差在 CPU 小于 0.00002 mm，在两款 GPU 小于 0.00038 mm。运行表的原始 SHA 随 LF/CRLF 换行而异，归一化后字节相同。

三项任务分别在 `reference`、`far` 运行相同的 68 步控制器。下列为通过短动作门槛的点数和翼螺钉实测转角。三个后端均测到立板接触但未越壁、导轨接触但未达到抬升门槛。全程成功与人工操作待测。

| 后端 | 原探针（共六点） | 筛选腕姿探针（共六点） | 筛选腕姿拧翼 reference / far | 旧显式 seed 701 拧翼 |
|---|---|---|---|---|
| Windows CPU 单环境 | 0 | 2 | 17.0° / 26.3° | 29.75° |
| Windows RTX 4070 双环境 | 1，螺钉 far 36.6° | 2 | 90.0° / 90.0° | 29.84° |
| Linux A800 双环境 | 1，螺钉 reference 20.4° | 2 | 90.0° / 90.0° | 29.98° |

[Windows 双环境逐点表](windows_cuda/POINTS.csv) · [Windows 汇总](windows_cuda/results.json) · [Windows SDK 与进程](windows_cuda/SDK.json) · [Linux 双环境逐点表](linux_cuda/POINTS.csv) · [Linux 汇总](linux_cuda/results.json) · [作业 142366 的 SDK 与文件摘要](linux_cuda/SDK.json)

独立留出 15 个格内点。CPU 用原三种进手倾角覆盖 15 点，两套 GPU 各覆盖 14 点。共同剩下立板 +10° 的 seed 1326。两端先重现该起姿的操作点及三条原路线的误差、关节步长和腕部余隙，再在同一位置细分进手倾角；−10°、−5°、+5° 均通过。−10° 路线最大目标误差 0.429 mm、最大关节步长 0.914 rad、腕部最小余隙 19.2 mm。该格保留，遥操可先试 −10°。细扫只用于离线核验，随机 reset 继续查表。[补测工具](../../../../tools/variation/audit_furniture_panel_approach.py) · [CPU 对照](cpu/panel_approach.json) · [Windows 双环境补测](windows_cuda/panel_approach.json) · [Linux 作业 142388 补测](linux_cuda/panel_approach.json)

三任务使用七个臂关节的原生高斯起始扰动，工作区接受标准差 0 至 0.01 rad。CPU 另取新 seed 及格内点测 0、0.005 rad，两组各覆盖每个角度层。零扰动立板 +10° 点在三个初选进手倾角均未通过；加测 −15° 路线后，最大目标误差 0.184 mm，腕部最小余量 25.7 mm。每次路径检查只代表所取初态。[替代进手侧原始读数](quiet_start.json)

下表以同一组八个种子的实测操作点计算跨度，单位 cm，顺序为世界 X × Y。该有限样本说明随机开关的实际效果；理论边界见运行表。FastenScrew 的极端朝向更易受整块交接板占地限制，可接受的区域在图中随角度收窄。

| 操作点 | 原生随机 | 旧显式域参考抽样 | 新工作区 |
|---|---:|---:|---:|
| 立板抓取点 | 6.03 × 4.07 | 8.85 × 3.74 | 13.31 × 7.16 |
| 桌面导轨抓取点 | 7.49 × 5.97 | 10.17 × 8.49 | 9.52 × 12.01 |
| 翼螺钉操作点 | 4.07 × 3.28 | 2.95 × 1.76 | 4.06 × 4.33 |

运行离线建图、后端检查和制图的方法如下。Windows 私有 SDK 的加载与身份检查沿用原 PR 的 launcher。两个后端分目录输出。

```sh
python -m tools.variation.build_furniture_workspace
python -m tools.variation.check_furniture_workspace --backend physx_cpu --output outputs/furniture-workspace-cpu
python -m tools.variation.audit_furniture_panel_approach --points outputs/furniture-workspace-cpu/POINTS.csv --output outputs/furniture-panel-approach
python -m tools.variation.plot_furniture_workspace --points outputs/furniture-workspace-cpu/POINTS.csv --output outputs/furniture-workspace-figures
```

**遥操试点。** 每项从 `reference` 开始，再试 `far`。立板记录夹住后能否越过壁顶及翻平；插轨记录从哪侧能提起并与槽口对准；拧翼记录哪侧能真实接触、何时需要重抓。每次回传运行版本、任务、样点、seed、env、进入侧和第一个受阻步骤。人工试用结果待采集。

## 2026-11-27 双环境复核

三项注册任务分别在位置分支 `c801c3c` 及其与 `main@00cc8e0` 的集成树 `fcf354f` 上实测。Windows PhysX CUDA 双环境、seed 717。先取两行 far 对照，再将两行初始化为 near；随后依次仅将 env1、env0 reset 至 far，局部调用省略 seed。六个方向的未选行位姿逐分量完全相同，所选行与同一物理环境的全量 far 对照满足 1×10⁻⁵ 分量误差门槛。两个版本的双向读数一致。索引逐任务保留两行操作前后实值、四元数、构造和 reset 参数、受测树、启动命令及 SDK 的原件入口。

还逐一将 5,799 个已编译格中心送入本家族数值回放入口，并检查全部命名预设。位置接口和既有行为通过 55 项家族测试。旧显式布局及工作区均用超出 float 表示范围的整数复现了异常类别错误，修后两个入口均返回 ValueError。 [逐行位姿、实际构造参数及原件索引](paired-reset-20261127.json)
