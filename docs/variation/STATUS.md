# 当前能力清单与验证边界

[Drawer / Socket 外观](DRAWER_SOCKET_APPEARANCE.md)已限定验收。抽屉 A 浅橡木与暖白、B 浅灰与石墨色通过 OpenDrawer／PickCharger 双环境验证及开闭审图。插座暖白／炭黑 PC 通过 InsertPlug 双环境验证。两者均覆盖原版恢复、随机复现和局部 reset 隔离。Long 单环境阶段验证只覆盖抽屉返工前版本。

[Drawer & Plug 十套家族外观](DRAWER_TEN_VARIANTS.md)已拍齐三个短任务的十套实景及固定方案恢复。OpenDrawer／PickCharger 随机及 A5 通过。InsertPlug 第二个方向的 Charger 像素判据未通过，随机复现未运行。旧对象的限定验收保留。

这是当前能力的集中入口；README和对象档案只作导航。对象索引共42项，其中14个对象为 `accepted_pilot`。各对象的任务覆盖和验证边界见对应条目。Meal限定技术验收通过，待整合/合并；依据[PR8-R2审阅](https://github.com/DennisXu626/DexArena-Variation/pull/8#pullrequestreview-5919739591)，集成状态见[PR8](https://github.com/DennisXu626/DexArena-Variation/pull/8)。本轮只做Git／CPU静态整合，不新增运行验证。

**Cabinet & Pouring 单门柜。** `cabinet_appearance` 独立选择 `original`、`oak_warm_white` 或 `sage_walnut`。Dennis 已确认两套柜体外观。OpenCabinet 原生闭门和 PickBottle 原生 90° 开门各 2 环境通过原版恢复、局部 reset 隔离和柜外材质对照。PickBottle 使用原版瓶子。验收限于这两个入口。[用法](CABINET_SINGLE_DOOR.md) · [实景与工程证据](evidence/cabinet_single_door/runtime_001/README.md)

**PourBeads 接收碗和模拟液滴。** Dennis 已确认 Ocean、Citrus、Violet 三款外观。PourBeads 两环境通过目标部件判色、原版恢复及局部 reset 隔离。碗在正式任务原位拍摄，16 颗原尺寸模拟液滴在独立实例中移到瓶外展示。完整倾倒、Long 和 A6 未测。[用法、实景与运行证据](evidence/pouring_bowl_beads/README.md)

## 1. 瓶身／瓶盖外观

| 字段 | 当前事实 |
|---|---|
| 状态、对象及任务 | 仓库已具备且限定验证通过。瓶身／盖，仅`CabinetPouringPickBottle-Sharpa-v1`和`CabinetPouringUnscrewCap-Sharpa-v1`；不是全部Cabinet子任务或Long接口 |
| 默认行为 | 新外观功能默认关闭，保留原生材质和任务初始化；外观、位姿开关独立 |
| 配置与实现 | [固定外观](../../examples/variation/cabinet_pouring/appearance.json)、[集合随机](../../examples/variation/cabinet_pouring/appearance_random.json)，经[运行示例](../../tools/variation/run_example.py)传入`variation`；[适配器](../../tasks/cabinet_pouring/variation.py)、[唯一运行catalog](../../tasks/assets/variation/cabinet_pouring/v1/catalog.json) |
| 可用方案与记录 | original＋Ocean／Citrus／Violet；真实标签替换、盖主体与既有非对称标记改色。回合固定，各env可独立选择，记录实际scheme／配置／最终表示；不是瓶与盖任意独立混配 |
| 实际验证 | M2及续篇001的1／2／4环境分项、两任务16环境默认／联合配置与重复局部reset、原三路RGB／human隔离。动态A／固定B／开口C与附着／自由盖绑定一致性含工程触发；原几何／物理对照保持 |
| 未验证边界 | 没有其它任务／手型、任意规模、长回合压力或完整机器人任务结论。工程阶段切换／已知盖角度图不是机器人真实拧盖 |
| 证据与验收来源 | [M2来源及验收映射](PROVENANCE.md)、[配置契约](CONFIG_CONTRACT.md)、[真实历史预览与绑定](../../assets/appearance/objects/cabinet_pouring/bottle/README.md)；已验收M2实现随团队基线保留，PR #1又验证了新区域下的默认／联合兼容性 |

## 2. Charger四套外观与正式接入

| 字段 | 当前事实 |
|---|---|
| 状态、对象及任务 | 仓库已具备且A4／A5限定通过。程序Charger主体＋双插脚，`DrawerPlugPickCharger-Sharpa-v1`、`DrawerPlugInsertPlug-Sharpa-v1` |
| 默认行为 | 省略或关闭`charger_appearance`保留原生original；启用后可显式选择original并读取scheme及catalog版本记录 |
| 配置与实现 | [默认](../../examples/variation/drawer_plug/charger_default.json)、[固定](../../examples/variation/drawer_plug/charger_fixed.json)、[集合随机](../../examples/variation/drawer_plug/charger_random.json)，按[正式调用说明](CHARGER_A4_A5.md)作为`gym.make` kwargs；[专用绑定](../../tasks/drawer_plug/charger_appearance.py) |
| 方案及参数源 | original／ivory_matte／navy_satin／copper_metal，唯一[charger-a3-v1 catalog](../../tasks/assets/variation/drawer_plug/v1/catalog.json)。对象档案只引用，不维护第二份参数源；无新UV／几何 |
| 实际验证 | 两任务各2env，四固定方案实际主体／双脚材质、相同seed原初态与几何／碰撞／接触材料／质量／惯量保持；指定集合随机两次重建复现；reset后两次渲染不重抽；仅env1换第三方案后env0状态／材料／记录与四路画面不变 |
| 未验证边界 | 原初态get_info及成功逻辑不变不等于机器人实际取放／插入；无物理步进或长期压力，不外推16env、其它手型或A6 |
| 证据与验收来源 | Bob [PR #2](https://github.com/DennisXu626/DexArena-Variation/pull/2)为A1–A3；[PR #4](https://github.com/DennisXu626/DexArena-Variation/pull/4)及[运行摘要](evidence/charger_a4_a5/results.json)为已验收A4／A5，实际测试提交`38b8474`；[Charger档案](../../assets/appearance/objects/drawer_plug/charger/README.md)保留来源与边界 |

## 3. 已有原范围初始位姿配置

| 字段 | 当前事实 |
|---|---|
| 状态、对象及任务 | 仓库已具备且限定通过。`CabinetPouringUnscrewCap-Sharpa-v1`的瓶最终有效B；关联PickBottle桌面目标。**PickBottle柜内A起点不受固定XY请求搬动**；Charger本轮没有新增位姿接口 |
| 默认行为 | 新位姿功能默认关闭，仍委托任务原生初始化及其原随机性；省略region_id仍用旧域C=(−.22,−.20)m、R=.15m |
| 配置与实现 | [默认关闭](../../examples/variation/cabinet_pouring/default.json)、[固定XY](../../examples/variation/cabinet_pouring/fixed_pose.json)、[原盘采样](../../examples/variation/cabinet_pouring/region_sampling.json)；[适配器](../../tasks/cabinet_pouring/variation.py)先解析，再由[UnscrewCap初始化](../../tasks/cabinet_pouring/cabinet_pouring_unscrew_cap.py)完成盖／颗粒关系与A→B |
| 参数及约束 | native／fixed／region，env_world下米制XY；完整底圈在区域内，中心半径从实际底圈几何扣除；identity wxyz、原派生高度与1mm reset间隙，非法请求报错并记录，不夹边或回退中心 |
| 实际验证 | M2固定／随机、原范围合法点与越界、记录／最终B关系、独立开关与局部reset；PR #1的2／4env旧域及关闭对照与冻结旧实现同seed状态一致，新域另列下一项 |
| 未验证边界 | 不支持任意对象／自定义区域／yaw／倾斜／自由z或机器人随机初始化。失败reset不承诺事务回滚；不承诺跨环境数、reset顺序或native与新增随机流逐样本一致 |
| 证据与验收来源 | [契约及默认委托](CONFIG_CONTRACT.md)、[M2验收来源](PROVENANCE.md)、[PR #1旧域回归说明](TABLE_XY_VALIDATION.md)。reset底部1mm间隙与放置成功最高.75mm是不同语义，原高度／倾斜／速度／放手／保持等非位置门槛不变 |

## 4. PR #1新增可选桌面XY区域

| 字段 | 当前事实 |
|---|---|
| 状态、任务及对象 | 仓库已具备且批准范围验证通过；PickBottle瓶桌面目标／引导盘／目标观测／位置谓词与UnscrewCap有效B初始化引用同一记录。只要求区域兼容，不精确继承一次终态 |
| 默认行为 | **不默认启用**；在`initial_pose.enabled=true`且显式选`cabinet_pouring.bottle_table.xy_v2`时启用。运行级选区，不新增逐环境动态切区接口；不同env仍可使用不同合法XY和外观 |
| 区域及配置 | env_world圆心**(−0.25,−0.35)m**，R=**.16m**约束完整底圈；中心采样半径=.16−actual_bottom_support_radius。保留旧ID／默认；新域是平移的较大盘，**不是旧域超集，也不是两盘并集**。入口：[固定](../../examples/variation/cabinet_pouring/table_xy_fixed.json)、[采样](../../examples/variation/cabinet_pouring/table_xy_sampling.json)、[外观联合](../../examples/variation/cabinet_pouring/table_xy_combined.json) |
| 实现 | [variation.py的共同记录与请求解析](../../tasks/cabinet_pouring/variation.py)，原父／子任务读取所选目标字段；不迁动柜体、机器人或PickBottle柜内起点；非位置成功门槛保持 |
| 实际验证 | 完整碰撞／连续中心域及柜门扫掠、测得机器人初态筛查；2／4env默认／旧区对照、中心＋8边界内点、越界拒绝、32个受控样本复现；9点动态A各释放2秒，末段.5秒持续满足原门槛及桌面支撑；两任务16env关闭／联合与两轮非连续局部reset，原RGB／human隔离 |
| 未验证边界 | **不是IK或机器人可达性、真实抓放／完整任务成功**。机器人几何结论只覆盖测得初态；9点2秒释放不是连续区域动力学全域或长期稳定性证明；隔离比较不推进物理。不扩大柜内范围／朝向／设施或任务家族 |
| 证据及验收来源 | [PR #1](https://github.com/DennisXu626/DexArena-Variation/pull/1)，已验收head`5191bc8`；[验证说明](TABLE_XY_VALIDATION.md)、[精简实测数据](TABLE_XY_MEASUREMENTS.json)。leader限定验收对应`VARIATION_M3_TABLE_XY_ACCEPTANCE_20261113.md`，原始记录由维护者保管；本轮按实际manifest哈希确认未改变已验收运行实现 |

## 5. Mouse 101408：限定ClickMouse外观与A4／A5

| 字段 | 当前事实 |
|---|---|
| 验收与集成状态 | leader已接受限定双环境结果；集成状态见[PR #6](https://github.com/DennisXu626/DexArena-Variation/pull/6)的合并记录。仅Mouse 101408、`OfficeDeskClickMouse-Sharpa-v1`，不扩到Long |
| 默认、方案与记录 | 省略/关闭`mouse_appearance`保留原生外观；original／ivory_matte／navy_satin，固定或指定集合随机、独立外观流、回合固定、实际方案与catalog版本记录 |
| 配置与唯一参数源 | [默认](../../examples/variation/office_desk/mouse_101408/default.json)、[固定](../../examples/variation/office_desk/mouse_101408/fixed.json)、[随机](../../examples/variation/office_desk/mouse_101408/random.json)；[运行catalog](../../tasks/assets/variation/office_desk/mouse_101408/v1/catalog.json)、[接口与绑定](MOUSE_101408.md) |
| 实际验证 | 2env physx_cuda原生加载/reset；三方案真实部件材料与RGB；随机复现/回合记录；修复后各方案的几何、碰撞、物理属性、初态和按钮target对照；两轮仅env1局部reset，env0状态/target/材质/记录与base/wrist/human三路RGB保持 |
| 原任务兼容修复 | 原GPU按钮target早于缓冲初始化；GPU移至已有_after_reconfigure，CPU保留原位置。与外观适配分别记载；不修改驱动参数、机器人、几何、质量、成功判定或Long，不在普通/局部reset新增全环境target重写 |
| 未验证边界 | 完整点击、Long、CPU后端运行、A6、大规模并行、修复前后内部warm-start轨迹等价。无用户env.step不等于引擎内部无warm-start；不宣称完整机器人成功 |
| 固定版本与来源 | 实际运行`78c9b2f212a50f4a9249acd30993dd9c6940d467`；已查收证据`daaec9c9cd9c30da432dd23c65a720ed1cfb382e`，[限定结果](https://github.com/DennisXu626/DexArena-Variation/blob/daaec9c9cd9c30da432dd23c65a720ed1cfb382e/docs/variation/evidence/mouse_101408/retest_001.json)、[Mouse档案](../../assets/appearance/objects/office_desk/mouse/README.md)、[PR #6](https://github.com/DennisXu626/DexArena-Variation/pull/6) |
| 历史记录 | 失败86071保留；复测86453完成25秒，GPU累计35/600秒。上轮墙钟71分54秒、超支26分54秒保留，不冲销；本次仅文档整合，GPU新增0 |

## 6. Meal Preparation 外观接入（限定技术验收通过，待整合/合并）

| 字段 | 当前事实 |
| --- | --- |
| 实现范围 | 午餐盒、盘子、勺子、面包和番茄。开盒、放面包、舀番茄及长任务四个 Sharpa 入口 |
| 配置与实现 | `meal_appearance` 默认关闭。提供原版和两套方案，支持固定选择、指定集合随机、按环境设置以及回合记录。[使用说明](MEAL_APPEARANCE.md)和[唯一运行 catalog](../../tasks/assets/variation/meal_preparation/v1/catalog.json) |
| 历史实测 | 86264 为旧基线加独立预览绑定，核对三方案的物理签名、受控任务判定和短任务回放。86563 为接入实现的双环境局部 reset 隔离，另测长任务双环境成本。86898 对照独立原版，四任务共 76 个槽的材质与纹理一致，恢复后的 env1 RGB 逐值一致 |
| 审阅补充 | PR8-R1 在 CPU 空渲染绑定下确认固定 seed、配置、环境数和 reset 顺序的 32 轮随机选择与记录可复现，未选 env0 随机流保持一致 |
| 未测范围 | 随机方案 GPU 渲染、更多环境、其它手型及 PartNet 午餐盒。放面包和舀番茄的历史回放未复现最终成功。长任务完成只用受控状态验证 |
| 审阅与证据 | [PR #8](https://github.com/DennisXu626/DexArena-Variation/pull/8)、[PR8-R1 审阅](https://github.com/DennisXu626/DexArena-Variation/pull/8#pullrequestreview-5918176986)、[证据与历史收据](evidence/meal_preparation/README.md)。限定技术验收通过，待整合/合并；[查收审阅](https://github.com/DennisXu626/DexArena-Variation/pull/8#pullrequestreview-5919739591)，集成状态见[PR8](https://github.com/DennisXu626/DexArena-Variation/pull/8) |

## 仍待实现／验证

[对象清单](../../assets/appearance/objects.csv)和[档案总索引](../../assets/appearance/README.md)记录42个逻辑对象状态。单门柜、瓶身／盖、抽屉／插座、Charger、限定ClickMouse及Meal五对象的验收范围分别以上述条目为准；Meal尚待PR8集成／合并，其余对象仍按待适配／无视觉／未加载状态保留。[下一物体候选](OBJECT_CANDIDATES.md)只是静态分析，其本身不提供新方案、GPU或A6结果。

完整机器人任务、策略训练、其它手型／规模、新物体适配、柜内扩区、自由yaw等仍需独立授权与验证。Meal随机方案真实GPU、PartNet午餐盒和完整机器人长任务成功未测；默认程序盒、固定方案双环境局部reset及恢复original的限定结论不外推。历史报告保留当时结论。

Meal [PR8-R2历史索引](evidence/meal_preparation/PR8-R2.md)和[PR8-R3整合记录](evidence/meal_preparation/PR8-R3.md)分别记录当时状态与本轮收尾。86264旧基线＋独立预览／回放仅作历史参考，不替代当前接入验收。执行层未批准、未合并。


## 7. Package Opening（PR9待最终合并）

三对象original＋variant_1／variant_2、OpenPackage／ExtractApple／Long三个Sharpa入口已实现，87021三任务各2env的限定运行证据已查收。当前implemented_pending_review，不增加accepted计数。配置／恢复原版／局部reset等证据与边界见[用法](PACKAGE_OPENING_APPEARANCE.md)及[PR9-R2索引](evidence/package_opening/PR9-R2.md)。CPU只补非连续／乱序环境索引、候选和绑定顺序身份检查；不代表GPU随机路径、完整机器人或压力测试。
