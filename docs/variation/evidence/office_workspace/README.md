# Office Desk 操作路径与位置采样

本目录对应 #43 的本地后继实现。三项短任务各用自己的机器人、设备碰撞体和操作路径计算可抽样区。真实桌面坐标采用米，接口的朝向是相对原型号绕世界 +Z 的角度，单位为度。旧显式域、任务阶段、原模型和原生接口见[原位置报告](../office_position_boundaries/README.md)。新模式默认关闭。OfficeDeskLong 的初始化走原生入口。

| Sharpa 短任务 | 真实操作点和筛选路径 | 范围和原始证据 |
|---|---|---|
| OpenLaptop，右手 | 从当前屏边接近，沿真实铰链追踪屏边到 90°，最后退出。对原生 40°、45°、50° 起始开度均筛正面、侧向两条路线，移动屏体与手掌同时参与碰撞检查。 | [机身 XY](laptop_xy.png) · [绕根转角](laptop_yaw.png) · [筛选记录](OpenLaptop_screen.csv) |
| TypeKeys，左手 | 同一左手指腹依次走 P、A、I、R、Enter。相邻键之间抬起再换位。路线包含接近、下压和释放，整体键盘和腕掌都须在该位置通过筛查。 | [键盘 XY](keyboard_xy.png) · [绕根转角](keyboard_yaw.png) · [筛选记录](TypeKeys_screen.csv) |
| ClickMouse，右手 | 以释放的左键面和实际按压轴为准，分别从前上方与壳侧进手，压下后退出。每条路线有不同的腕掌朝向。模拟器分别读取左右键行程、接触和原生成功。 | [鼠标 XY](mouse_xy.png) · [绕根转角](mouse_yaw.png) · [筛选记录](ClickMouse_screen.csv) |

## 计算与判读

从原生 CPU 的标称回合捕获七个臂关节的世界位置、轴、限位、实际指尖或指腹、手腕与手掌碰撞网格，及真实机身、桌面和活动件。鼠标、键盘、笔记本各有独立输入，记录设备和机器人资产哈希。对本回合原生机器人起点作有界逆运动学，每一段以先前关节解接续。指腹位置和手掌相对于指腹的方向共同约束解。鼠标／键盘沿设备实际按压轴移动。[原生输入快照](frames) · [路径与网格构建](../../../../tools/variation/office_workspace/build.py) · [运动学与碰撞检查](../../../../tools/variation/office_workspace/kinematics.py)

筛选使用 4 cm 粗格，未整格通过的区域细分为 2 cm。角点、中心和一处非对称内部点须有**同一条路线**通过。路径插值、关节限位、指尖误差、相邻解变化和碰撞余量的阈值见构建器。前臂、手腕、掌部等真实碰撞体沿长轴分段包围，按随动关节变换与桌体、设备包围盒相测。笔记本屏体使用随开启角变化的有向包围盒。筛选记录中 0 为通过，1 为指尖误差，2 为关节变化，3 为非目标碰撞余量，4 为设备占地越过桌面余量。运行表只保留通过的格，包含支持的进手路线。有限搜索窗口的外边界表示本次探索止于此；薄接触、全部自碰撞和抓按力须由物理试验和遥操验证。格内仍有插值误差。[运行表](../../../../tasks/office_desk/workspace_maps)

运行时等概率选已筛过的朝向，同朝向按有效格的面积抽样，随后在格内连续均匀取 XY。同一格有多条路线时只计一次面积。每个任务重播 8,192 次随机抽取，逐次核对成员关系与精确重现。另用建图后固定的独立随机流，在每档朝向抽 24 个格内点复算路径，笔记本另抽连续开度。三项均有 72/72 个独立点找到路线。分角度面积、实测频次和逐点误差保存在审计报告。[鼠标审计](ClickMouse_audit.json) · [键盘审计](TypeKeys_audit.json) · [笔记本审计](OpenLaptop_audit.json)

## 构造与复现

```python
import gymnasium as gym
import tasks

env = gym.make("OfficeDeskClickMouse-Sharpa-v1", position_workspace=True,
               obs_mode="state", control_mode="pd_joint_pos", reconfiguration_freq=0)
env.reset(seed=717)
env.reset()  # 下一个随机布局
env.reset(options={"workspace_placement": {"0": "near"}})
env.reset(options={"workspace_placement": {"0": "far"}})
print(env.unwrapped.position_workspace.episodes[0])
env.close()
```

每项均提供 `reference`、`near`、`far`、`left`、`right`。近和远改变世界 X，左右改变世界 Y。以固定预设的区域中心选取近远／左右对照，`reference` 优先复现原标称根。完整数值使用原设备的 `<device>_xy_m` 和 `<device>_yaw_offset_deg` 两个字段，域外、缺字段、互相冲突或 env 键不匹配的请求在写状态前拒绝。旧 `position_layout` 独立保留，仍可复现旧报告里的边界／失败点。固定预设及数值请求不推进布局计数，状态恢复走原生恢复路径。实际选中环境的采样表版本、seed、抽取编号、世界 XY 和相对转角可从 `episodes` 读取。

并行环境先全量设 seed，再在下一次 reset 的 options 里传 `env_idx=[1]` 和 `workspace_placement={"1":"far"}`。分别检验未选环境物理、阶段、控制器、任务与位置随机序列；TypeKeys 另查目标键提示。为复现动作，请使用逐点数据中的机器人、后端、make 参数、seed、env 索引及完整 reset 顺序，录制恢复时检查是否传入保存的场景状态。

## 本地再生成

从仓库根目录运行，需要原生场景、授权资产、NumPy、SciPy、Matplotlib。构建器在安装 Numba 的 CPU 环境下可加速；冻结帧到生成的表和图之间无需加载仿真器。三个任务分别运行构建及验证。

```text
python tools/variation/office_workspace/capture.py docs/variation/evidence/office_workspace/frames
python tools/variation/office_workspace/build.py --task ClickMouse
python tools/variation/office_workspace/build.py --task TypeKeys
python tools/variation/office_workspace/build.py --task OpenLaptop
python tools/variation/office_workspace/audit_map.py
python tools/variation/office_workspace/verify.py --task ClickMouse --backend physx_cpu --output outputs/workspace/ClickMouse
```

Windows CUDA 使用本仓已有的核验 SDK 启动器，传同一 checker、任务和 `--backend physx_cuda`。本地证据汇总、动作结果和逐点入口见[实测报告](RESULTS.md)。

在归档的 CPU 逐点数据上可额外运行 `python tools/variation/office_workspace/check_cpu_controls.py outputs/workspace/compatibility.json`，复核原 PR 的标称序列、保存状态恢复、Long 原生重播、随机起姿以及与主动动作同长的被动开盖。

## 2026-11-27 双环境复核

TypeKeys 在全量 near 后首次局部 reset 的第一次 PhysX fetch 将未选行的绿色提示恢复到了上一轮标称位置，平面偏差 28.28 mm。修复在当前键的姿态计算完成后，按真实刚体 ID 将所选标记写回 PhysX，并按物理场景的 float32 精度给出首次读回。测试使用实际键 link、序列索引、标记 XYZ 和四个机位，另覆盖标记行与环境号逆序。

Windows RTX 4070 Laptop 使用 `main@00cc8e0` 与 `fa6aa11` 的集成树 `bc1a11f`。OpenLaptop、TypeKeys、ClickMouse 均先仅 reset env1 至远点，再仅 reset env0 至标称点并切换外观。六次未选行同机位 RGB 逐像素相同；TypeKeys 两行标记与当前目标键帽预期位置最大分量误差 5.97×10⁻⁸ m。两条键盘类任务在两次局部 reset 均读回请求的 `variant_1` 机身和 `variant_2` 键帽，鼠标读回 `ivory_matte`。

从索引中 `archive.root` 进入团队原件目录。每个 `verified-任务/output/任务/` 下，`input.json` 记录构造参数及资产，`environment_1.json` 和 `environment_0.json` 分别记录所选行、同次请求、两行实值、材质、逐阶段控制目标及原帧。TypeKeys 的 `marker-trace.json` 包含 fetch 和标记写入前后读数。三项任务共 100 张本轮原帧，`SHA256.json` 可逐份查验。

还逐一将 366 个已编译格中心送入本家族数值回放入口，并检查全部命名预设。位置接口和既有行为通过 26 项家族测试。当前主线组合另通过 28 项 Office 测试。旧显式布局及工作区均用超出 float 表示范围的整数复现了异常类别错误，修后两个入口均返回 ValueError。 [逐行位姿、实际构造参数及原件索引](paired-reset-20261127.json)
