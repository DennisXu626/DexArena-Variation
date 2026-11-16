# DexArena Variation

这是基于 [官方 DexArena](https://github.com/SIPAIR-Elastic/DexArena) 的团队开发仓库。我们为灵巧操作任务增加物体外观、任务物体初始位姿（位置和朝向）配置，以及相邻子任务的区域对应。物体外观与位姿优先，场景背景扩展后置；最终目标是覆盖全部正式任务，已有验收覆盖 Cabinet／Charger 两家族四任务；本 PR 另交付 Meal 五对象、四个 Sharpa 任务的接入与限定证据，待独立审验负责人最终审验。

外观变化保持视觉／碰撞几何及物理参数不变；位姿只控制明确授权的任务物体，不自动随机化机器人。底层环境由ManiSkill管理，物理和渲染由SAPIEN提供，原对象素材仍按官方授权渠道取得。运行试点不需要AutoDemo算法工程、PPO、教师／学生模型、Dexonomy或任何训练检查点。

## 当前能做什么

试点为Cabinet & Pouring家族的：

- `CabinetPouringPickBottle-Sharpa-v1`：从柜内取瓶放到桌面目标区域，柜内起点保持原任务行为。
- `CabinetPouringUnscrewCap-Sharpa-v1`：从桌面放置瓶开始拧盖，可在原区域或显式选择的新XY区域配置合法瓶位姿。

已有原版＋Ocean／Citrus／Violet三种外观，实际替换瓶标签、调整盖子和非对称转动参照；支持明确指定或从指定集合随机选择，回合内固定，动态瓶／固定瓶／开口瓶及附着盖／自由盖保持同一逻辑方案。标签、品牌和原红条可以替换，但盖子必须有清楚且非对称的转动参照，仅均匀色或难分辨的周期图案不够。

Cabinet两个任务已有16环境的GPU批量局部reset（重置选中的环境）及RGB渲染实测；检查了未选环境的物理状态、材质与画面隔离，结果继承已验收M2及续篇001。

Charger外观支持`DrawerPlugPickCharger-Sharpa-v1`和`DrawerPlugInsertPlug-Sharpa-v1`：original仍默认，ivory_matte／navy_satin／copper_metal可固定或集合随机选择；两任务各2环境的A4／A5已通过，包含物理／初态一致性、回合记录和局部reset状态／RGB隔离。Bob A1–A3材质交付与本线接入验收分开，参数只保存在一个[Charger catalog](tasks/assets/variation/drawer_plug/v1/catalog.json)，用法与实际证据见[Charger说明](docs/variation/CHARGER_A4_A5.md)。

Meal Preparation 已在 [PR #8](https://github.com/DennisXu626/DexArena-Variation/pull/8) 提交五个对象的外观方案与四个 Sharpa 任务入口，待最终审验。[Meal 使用说明](docs/variation/MEAL_APPEARANCE.md)和[历史运行证据](docs/variation/evidence/meal_preparation/README.md)包含双环境隔离、原版恢复及适用边界。

**本次补交仅整理历史证据并做静态检查。** 以上不代表全部任务、任意并行规模、范围扩大、完整机器人任务成功、A6或强化学习能力。详见[当前能力和限制](docs/variation/STATUS.md)、[来源与版本](docs/variation/PROVENANCE.md)。

本分支另提供 `cabinet_pouring.bottle_table.xy_v2`：圆心(−.25,−.35)m、底圈区域R=.16m，保留旧默认。它是平移后的较大圆盘，**不包含全部旧位置**。完整碰撞补测和新区域检查单列于[M3验证说明](docs/variation/TABLE_XY_VALIDATION.md)，不能把M2历史通过当成本次新区域证据。

当前默认开关、任务／对象、配置、实测边界及实现／证据／验收来源统一列于[能力清单](docs/variation/STATUS.md)；[下一物体候选分析](docs/variation/OBJECT_CANDIDATES.md)不代表已适配或A6完成。

## 代码导航

| 路径 | 做什么 | 谁先看 |
|---|---|---|
| [variation.py](tasks/cabinet_pouring/variation.py) | 外观绑定、位姿请求、共用区域和回合记录 | 外观、位姿、集成 |
| [cabinet_pouring_long.py](tasks/cabinet_pouring/cabinet_pouring_long.py) | 共用任务、A／B／C物体表示、reset及批量渲染兼容入口 | 集成负责人协调修改 |
| [PickBottle子任务](tasks/cabinet_pouring/cabinet_pouring_pick_bottle.py) | 柜内初始化、放瓶目标与子任务接口 | 位姿、集成 |
| [UnscrewCap子任务](tasks/cabinet_pouring/cabinet_pouring_unscrew_cap.py) | 桌面初始化、最终固定B表示与子任务接口 | 位姿、集成 |
| [按物体外观档案](assets/appearance/README.md) | 十家族对象状态、已验收试点和 Meal 待审验接入 | 外观、素材整理 |
| [运行外观catalog](tasks/assets/variation/cabinet_pouring/v1/catalog.json) | 既有运行发布副本，运行仍读取此路径 | 外观、集成 |
| [Charger接入](tasks/drawer_plug/charger_appearance.py)、[配置示例](examples/variation/drawer_plug/)、[证据](docs/variation/evidence/charger_a4_a5/README.md) | 两个DrawerPlug子任务的外观配置及A4／A5边界 | 外观、集成、验收 |
| [tasks/robots/](tasks/robots/)、[tasks/scene_builders/](tasks/scene_builders/)、[tasks/config/](tasks/config/) | 上游机器人、场景及注册／物理配置 | 了解来源；常规外观工作不需要修改 |
| [Meal 接入](docs/variation/MEAL_APPEARANCE.md)、[证据及收据](docs/variation/evidence/meal_preparation/README.md) | 开盒、放面包、舀番茄和长任务的外观配置与验证边界 | 外观、集成、验收 |
| [examples/variation/](examples/variation/) | 已有试点配置及本机路径模板 | 所有人 |
| [tools/variation/run_example.py](tools/variation/run_example.py) | 读取配置，加载／reset，保存记录及可选首帧 | 使用者、集成 |
| [tools/variation/check_static.py](tools/variation/check_static.py) | 不导入仿真的CPU静态检查 | 所有人 |
| [环境与素材](docs/variation/SETUP.md)、[配置契约](docs/variation/CONFIG_CONTRACT.md)、[当前进度](docs/variation/STATUS.md) | 准备资源、理解接口和限制 | 所有人 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 分支、PR、审阅、验证与交付规则 | 所有人 |

三条阅读路线：

1. **做外观**：先看[本轮分工与交付](docs/variation/TEAM_APPEARANCE.md)和[对象档案](assets/appearance/README.md)，再参考既有catalog及预览样例。实习同学交付部件映射、方案／素材、同条件对照和复现说明；Dennis统一组织正式任务接入及A4／A5验收。模型预览与真实任务画面分别标注，不能相互替代。
2. **做初始位姿**：先看 `fixed_pose.json`／`region_sampling.json`、契约中的env_world坐标／米／wxyz单位，再沿 `REGION`、PickBottle目标、UnscrewCap最终B初始化阅读。不能只改父类临时初态，因为子类reset会继续覆写。
3. **做集成**：先看契约、父任务和两个子类的接入点，再检查默认关闭、每env记录、局部reset与渲染隔离。共用入口提前协调；外观与位姿当前共用一个适配模块，不各造一套框架。

## 从零开始

### 1. 克隆和静态检查

使用自己的GitHub认证，不共享token；缺少仓库开发权限时联系Dennis。以下克隆命令从存放代码的父目录运行，其余命令都从仓库根运行：

```bash
git clone https://github.com/DennisXu626/DexArena-Variation.git
cd DexArena-Variation
git remote add upstream https://github.com/SIPAIR-Elastic/DexArena.git
python tools/variation/check_static.py
```

预期静态检查输出JSON，`status` 为 `passed`。它只解析Python语法、配置和团队文档链接，不导入环境。origin为团队仓库，upstream只读参考；本次集成固定官方 `e7d5c49d079153e77da1ce2bfde16edf67ee7fa8`，不自动合并更新的上游改动，不向官方推送。

原上游 `libs/Isaac-GR00T` 子模块锁定记录保留，但试点不依赖它，不需要递归克隆。完整官方祖先历史、机器人资源、Apache-2.0许可证和已有NOTICE保留；[固定基准的官方首页与署名](https://github.com/SIPAIR-Elastic/DexArena/blob/e7d5c49d079153e77da1ce2bfde16edf67ee7fa8/README.md)属于上游成果。

### 2. 准备环境和资源

按[环境与素材说明](docs/variation/SETUP.md)申请已验证的Linux GPU环境，获取有授权的Cabinet对象包并放入仓库内可写副本。已验收Python3.10、torch2.6.0、SAPIEN3.0.3、ManiSkill3.0.0b22、numpy2.2.6、gymnasium0.29.1；新机器安装、Windows仿真和其它核心版本未重新验证，不承诺任意笔记本直接运行。

机器人网格已跟踪在Git中；对象包来自HF，桌面来自ManiSkill安装素材。不要把整个HF数据集、模型或示范下载进仓库。原任务会在对象附近生成URDF（机器人／物体的结构描述文件），因此不要直接指向共享只读资产。

```bash
mkdir -p .local
cp examples/variation/paths.example.env .local/paths.env
# 按SETUP.md编辑本机路径，并准备对象素材后：
source .local/paths.env
"$DEXARENA_PYTHON" --version
```

### 3. 单环境与双环境示例

下列命令只供**已获资源许可**的环境运行；代码推送不授权使用GPU。本轮没有执行这些命令。脚本只加载、reset并可保存一次初始化画面，不执行策略或完整任务。

```bash
"$DEXARENA_PYTHON" tools/variation/run_example.py \
  --config examples/variation/cabinet_pouring/appearance.json \
  --output outputs/variation/appearance_1 --task UnscrewCap --num-envs 1 --seed 7 --render-once

"$DEXARENA_PYTHON" tools/variation/run_example.py \
  --config examples/variation/cabinet_pouring/combined.json \
  --output outputs/variation/combined_2 --task UnscrewCap --num-envs 2 --seed 7 --render-once
```

预期各输出目录有 `manifest.json`、`state.json`、启用variation时的 `episodes.jsonl`，以及 `env_0.png`（双环境还有 `env_1.png`）。回合文件记录实际方案、最终位姿、区域及环境索引；manifest每次运行记录一次源码／小素材来源，**不递归重哈希全部资产**。构造器也可能执行reset，不能把记录行数简单当成命令手动reset次数。默认全关闭时没有新增variation回合记录。

配置如何选：

| 配置 | 作用 | 适用任务 |
|---|---|---|
| [default.json](examples/variation/cabinet_pouring/default.json) | 关闭两个功能，委托原生行为 | 两任务 |
| [appearance.json](examples/variation/cabinet_pouring/appearance.json) | 明确外观；env0 Ocean、env1 Citrus | 两任务 |
| [appearance_random.json](examples/variation/cabinet_pouring/appearance_random.json) | 从3方案集合按回合选择 | 两任务 |
| [fixed_pose.json](examples/variation/cabinet_pouring/fixed_pose.json) | 原范围中心固定瓶位姿 | UnscrewCap |
| [region_sampling.json](examples/variation/cabinet_pouring/region_sampling.json) | 原合法盘内按面积采样 | UnscrewCap |
| [combined.json](examples/variation/cabinet_pouring/combined.json) | 外观＋合法固定位置，逐env覆盖 | UnscrewCap；PickBottle仅外观和共同目标定义，仍从柜内开始 |
| [outside_expected_error.json](examples/variation/cabinet_pouring/outside_expected_error.json) | 演示明确越界会报错 | UnscrewCap，预期失败样例 |
| [table_xy_fixed.json](examples/variation/cabinet_pouring/table_xy_fixed.json) | 新区域中心固定XY | UnscrewCap |
| [table_xy_sampling.json](examples/variation/cabinet_pouring/table_xy_sampling.json) | 新区域按面积盘采样 | UnscrewCap |
| [table_xy_combined.json](examples/variation/cabinet_pouring/table_xy_combined.json) | 新区域＋不同环境外观／合法XY | UnscrewCap；PickBottle只改变共同目标，柜内起点保持 |

更换 `--config` 即可使用其它示例。运行取瓶试点可使用 `--task PickBottle --config examples/variation/cabinet_pouring/appearance.json`，其它参数同上；取瓶采用新区目标时改用 `table_xy_combined.json`。区域只支持原区和新增的固定批准记录，不能任意扩大或改变高度／朝向，不能把取瓶起点搬到桌面；相邻任务要求区域兼容，不精确继承某次终态。详见[契约](docs/variation/CONFIG_CONTRACT.md)。

## 团队怎样开发

本轮按任务家族分工：Dennis负责2个家族，两位实习同学各4个家族；每人先交一个外观样例，再分批推进。对象范围、首个样例、交付包及职责边界统一见[本轮外观协作安排](docs/variation/TEAM_APPEARANCE.md)。位置规则暂由Dennis集中制定，本轮不向实习同学分发位置实现任务。

main是供大家使用的集成版本，开发必须从最新main新建任务分支，如 `feat/bottle-appearance`、`feat/pose-regions`、`fix/reset-isolation`，一个分支对应一件工作。禁止直接在main开发或随手推送，不强推main。

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/bottle-appearance
# 修改后检查，只添加本次明确文件：
git status --short
git diff --check
git diff
python tools/variation/check_static.py
git add -- tasks/assets/variation/cabinet_pouring/v1/catalog.json
git diff --cached
git commit -m "说明外观变更"
git push -u origin feat/bottle-appearance
```

到GitHub创建PR，写清目标、改动、验证、截图／证据和剩余问题。其他成员的PR由Dennis或指定负责人审核后合并；项目leader Dennis本人的PR免除额外成员审阅／批准，完成必要检查并确认后可自行合并。冲突先解决，公共任务文件／接口修改提前协调；不要随手优化、改物理或扩大范围。main强制保护取决于账户支持及实际服务器配置，不能把文档约定当成已生效保护；详见[贡献规范](CONTRIBUTING.md)。

遵循最小实现、最小修复、最小测试：外观查真实效果及物理不变，位姿查合法性／最终记录／隔离；文案改动不跑完整GPU验证。每次交付同步配置、用法和限制，成功／未完成／未验证分开写。不提交数据集、输出、缓存、模型、凭据或个人机器配置，不共享token。

## 来源与许可

保留 [Apache-2.0 LICENSE](LICENSE)、[上游引用](docs/citation.bib)、[既有第三方NOTICE](utils/pi05_utils/NOTICE)和模型来源说明。原始DexArena、ManiSkill／SAPIEN及对象素材归各原作者；本团队新增内容只限已标明的variation实现、小贴图和协作入口，详见[来源映射](docs/variation/PROVENANCE.md)。私有仓库不替代第三方数据许可。

Meal 本轮补充资料及提交对应性集中见[PR8-R2证据索引](docs/variation/evidence/meal_preparation/PR8-R2.md)。执行层只完成证据与文档收尾，最终验收以 PR #8 审阅为准。
