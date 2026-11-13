# Cabinet M2 最小可运行契约

这是已验收M2契约的团队使用版，历史交付由维护者保管。**Dennis最新决定已覆盖旧限制：瓶身原标签/品牌可替换；盖子原红条和颜色可替换，但必须有清楚的非对称转动参照。** 本轮不增改视觉/碰撞几何、不增加瓶盖UV；重用已有偏心顶条与侧刻度，使用高对比颜色。

## 入口与开关

给两个正式试点任务的 `gym.make(..., variation=config_dict)` 传入配置；不新增任务ID、不改训练工具。JSON加载由调用者用标准json完成，不建设通用配置框架。

```python
config = json.loads(Path("examples/variation/cabinet_pouring/combined.json").read_text())
env = gym.make("CabinetPouringUnscrewCap-Sharpa-v1", num_envs=2,
               obs_mode="state", render_mode="rgb_array", variation=config)
env.reset(seed=7)
```

`appearance.enabled` 与 `initial_pose.enabled` 独立，默认均false；两者都关闭时不构造适配器，不抽新随机数、不加载/绑定variation材质、不额外写物体pose。原任务原有随机化仍保留。该默认委托与 `initial_pose.mode=native` 的对照有独立运行数据，见[当前状态](STATUS.md)。

## 字段

| 字段 | 本轮支持 |
|---|---|
| version | `cabinet-pilot-v1`，契约标签；源码提交、素材版本、安装环境另记manifest |
| seed | 新增随机流的整数种子；外观与region采样按功能、真实env_idx分离；不消耗原任务Torch流 |
| manifest_ref / config_ref | 回合记录中的引用；固定哈希/代码/资产/后端等放运行manifest，不每回合重复计算资源哈希 |
| record_path | 可选JSONL输出路径，父目录由调用者创建；未指定时记录在 `env.unwrapped._variation.records` |
| appearance.enabled | 全局开关；只有开启才读取有限方案目录和准备材质 |
| appearance.mode | `explicit` 或 `random_choice` |
| appearance.scheme_id | `original`、`ocean`、`citrus`、`violet`。未知ID报错 |
| appearance.scheme_ids | random_choice的非空可用ID集合，均匀选择 |
| initial_pose.enabled | 全局独立开关；引用唯一原版桌面region |
| initial_pose.mode | `native`委托原 `_placed_bottle_xyz`；`fixed`明确XY；`region`按原面积均匀盘独立采样 |
| initial_pose.xy_m | fixed模式的world/local-env XY，单位m |
| initial_pose.z_m | 可省略，由实际 `-source_z_lo+.001` 派生；指定时必须保持该原值 |
| initial_pose.quaternion_wxyz | 本轮仅原生identity `[1,0,0,0]`，不扩大原朝向范围 |
| initial_pose.region_id | 仅 `cabinet_pouring.bottle_table.v1` |
| per_env | 字符串化真实索引→appearance/initial_pose请求覆盖。开关是运行级；各环境可有不同方案/合法位姿/采样请求 |

在reset的options内可给 `variation` 请求覆盖，作用只限本次被reset环境：先全局配置，再该env配置，再本次全局覆盖，再本次该env覆盖。可同时设置本次 `config_ref`。

```python
env.reset(options={"env_idx": torch.tensor([1], device=env.unwrapped.device),
                   "variation": {"config_ref": "episode-choice-v2",
                     "per_env": {"1": {"appearance": {"scheme_id": "violet"},
                        "initial_pose": {"mode": "fixed", "xy_m": [-.20, -.22]}}}}})
```

**兼容性状态：续篇001已在任务层修复“先渲染→局部reset→再次渲染”，两个试点16环境及原有RGB相机路径通过。** 结论继承自M2验收，本次迁移仅作静态检查；核心版本与未选环境隔离边界见[当前状态](STATUS.md)。

## 区域与最终有效状态

唯一启用配置的区域记录在 `tasks/cabinet_pouring/variation.py:REGION`：env_world，XY圆盘，中心(−.22,−.20)m、R=.15m、table top z=0。前段PickBottle目标与后段UnscrewCap初始化均消费它；本轮只支持原记录，不开放修改中心/半径/固定设施。

含义是**完整瓶底支撑圈**在原圆盘内，中心允许半径为 `.15 - actual_bottom_support_radius`。实际几何值从碰撞得到。明确越界请求报错，记录失败，不缩小范围、不回退中心。

UnscrewCap先解析配置得到逻辑瓶pose，随后原生放瓶/盖/颗粒并最后激活固定B；实际记录读取最终B。盖的相对安装和16颗粒的原生局部packing＋±0.2*particle_radius抖动保留。inactive表示的停车/固定性由原机制处理。

PickBottle的柜内起点及柜体保持原生；本轮其initial_pose开关只接共同**目标区域定义**，不把柜内瓶挪到桌面，fixed请求只用于UnscrewCap。这个边界在示例中明确。

原成功条件的高度、倾斜、速度、放手、连续保持等不变。reset仍预留1mm底部间隙；前段成功要求底圈最高≤.75mm，两者语义分开，不强改阈值来“对齐”。未扩大位置或朝向范围，未改机器人。

## 外观绑定与回合记录

三瓶句柄`source/source_fixed/source_open`与三盖句柄`cap/cap_fixed/cap_twin`均预先使用本回合选定方案；正常阶段切换不重抽、不恢复原版。label材质槽替换纹理，瓶其它槽改色，盖主体和现有非对称标记改色/粗糙度/金属度。所有UV和几何保持原值。

原生file mesh材质已按环境独立；程序标记的显式材质原来共享，本线仅在原生builder每环境构造视觉组件时复制这些材质。没有重建几何、增加shape或修改共享ManiSkill。有限纹理池在构建阶段准备，缓存的纹理图只读共享。

每个被reset环境记录：manifest_ref、config_ref、env_idx、episode_index、实际appearance、最终world pose（m,wxyz）、region_id、representation、cap位置和status；失败追加error。没有逐回合哈希全部资产。默认关闭不新增记录器。

固定配置、相同新增种子/环境数/reset顺序的随机序列有对照检查；不承诺跨环境数或不同reset顺序逐样本相同。`mode=native`全批请求复用原Torch调用，混合fixed/native时不承诺与全原生路径耗用完全相同的随机序列。
