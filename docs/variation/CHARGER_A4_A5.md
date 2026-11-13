# Charger正式接入：本轮A4／A5短检通过

本分支依赖Bob [PR #2](https://github.com/DennisXu626/DexArena-Variation/pull/2)的已审阅提交5185f1dd61f2de88ab7d4ada7a2ef77f01e6b207。Bob交付部件／材质与单环境预览A1–A3；本分支负责正式接入和A4／A5，不要求Bob补做。经本轮单独授权，在现有GPU环境完成两任务各2env短检，**A4／A5均通过限定检查**；没有训练或完整机器人任务成功结论。

## 现有参数与最小接入

直接读取[Bob原catalog](../../tasks/assets/variation/drawer_plug/v1/catalog.json)，版本charger-a3-v1。original、ivory_matte、navy_satin、copper_metal全部保持其参数；本体变色／粗糙度／金属度，双插脚保留原版参数。不新增贴图、UV或几何，不复制第二份catalog。

只向PickCharger／InsertPlug开放可选任务kwarg `charger_appearance`；省略或enabled=false沿用原生构建和reset，不分配外观随机流／改绑材质，original仍是默认。开启时仅在原有Charger视觉builder每环境构建时隔离显式材质，并在子任务原生初始化结尾应用选中参数；原生RGB观测取得前完成绑定，未改机器人、位姿、碰撞、接触材质、质量或成功判定。

```python
import json
import gymnasium as gym
import tasks

config = json.load(open('examples/variation/drawer_plug/charger_fixed.json'))
env = gym.make('DrawerPlugPickCharger-Sharpa-v1', num_envs=2,
               obs_mode='rgb', render_mode='rgb_array', **config)
obs, info = env.reset(seed=7)
# Read actual scheme IDs, catalog version and per-reset records:
adapter = env.unwrapped._charger_appearance
print(adapter.schemes, adapter.catalog['version'], adapter.records[-2:])
```

三个[示例](../../examples/variation/drawer_plug/)是构造kwargs，不接入训练工具。InsertPlug使用相同kwargs替换任务ID。explicit默认scheme_id=original；random_choice从非空scheme_ids选择。独立外观seed和每env生成器不消费任务Torch随机流。同seed／配置／环境数／reset顺序（含构造时原生reset）可复现，跨环境数／顺序不作逐样本承诺。

局部reset只重新选择指定env；不提供step中改色API，回合内不重新抽样：

```python
import torch
env.reset(options={'env_idx': torch.tensor([1], device=env.unwrapped.device),
                   'charger_appearance': {'per_env': {'1': {'scheme_id': 'copper_metal'}}}})
```

记录字段为env_idx、episode_index、scheme_id及catalog_version；不逐回合重算全资产哈希。默认关闭没有额外记录器，原生original未绑定catalog；开启并指定original则有版本和选择记录。记录为本实例内存列表，调用者可在回合结束写出；短检脚本保存它们。

## 静态与运行边界

```bash
python tools/variation/check_static.py
python tools/variation/check_charger_a4_a5.py --static
```

第二项用AST对照Bob head：除构造／Charger构建的显式材质隔离、两子任务初始化末端绑定外，其余已有方法保持，包括成功条件、机器人初始化及物理逻辑。静态不证明实际材质隔离或成功条件运行回归。

仅在获得**本轮新单卡预算**并按现有调度规范分配GPU后运行一次短检：

```bash
python tools/variation/check_charger_a4_a5.py --output outputs/charger_a4_a5/run_001
```

脚本用physx_cuda、每任务2env，比较原生默认与四固定方案的几何／碰撞／接触材质／质量／惯量／原初态及初始判定；重建两次检查受控随机序列。A5从ivory_matte／navy_satin开始，仅reset env1为copper_metal，不推进物理，比较env0完整状态／材质／记录和原RGB／human画面。复用原相机，失败保留原始状态与栈；不训练、不工程触发成功，不扩展任务。

## 本轮实际结果

测试源码提交38b847444b6d2587068348e0047f09e33b98f2e8，ManiSkill3.0.0b22／SAPIEN3.0.3／Torch2.6.0／Python3.10.22，physx_cuda、原相机，两个任务各2环境。使用完整Git源码私有副本及只读Drawer资产；不是Bob的另一Torch环境，也没有升级依赖。本轮新增运行证据与Bob A1–A3历史预览分开。

| 检查 | PickCharger | InsertPlug |
|---|---|---|
| 原生默认与四固定方案、本体／双插脚实际参数 | 通过 | 通过 |
| 同seed完整初态、几何／碰撞／接触材质／质量／惯量与原生一致 | 通过 | 通过 |
| 相同配置、seed及reset顺序的集合随机序列两次重建复现 | 通过 | 通过 |
| 回合内两次渲染方案／记录固定，实际ID／catalog版本可读 | 通过 | 通过 |
| 初态get_info与原生一致、成功判定源码保持 | 通过 | 通过 |
| 仅env1由navy_satin切为copper_metal，env0保持ivory_matte | 通过 | 通过 |
| env0完整状态／材料／记录及原RGB／human像素不变 | 通过 | 通过 |

两任务A5的base_camera／task_wrist_camera／wrist_camera／human未选环境像素差均0。RGB尺寸为2×256×256×3、2×256×256×3、2×240×320×3，human为2×720×1280×3。无物理步进、相机固定；选中环境机器人位置变化是原生局部reset，不是修改初始化。成功回归仅核对原初态和既有函数未变，没有构造完整成功、机器人抓取或插入执行。

[实际材料、随机序列、状态与隔离摘要](evidence/charger_a4_a5/results.json)来自运行记录，作为观测证据而不是第二份catalog；[原RGB对照](evidence/charger_a4_a5/README.md)保留任务实景。原始完整状态、逐方案物理快照、48张相机PNG和运行manifest由维护者单独交付，不上传服务器路径或原始日志。另用CPU重读8份状态及物理快照、A5状态和前后PNG独立复核；本机CPU审计Torch2.11.0不等于仿真环境版本。

单次作业实际GPU分配29／600秒，退出0:0，已完成且无活动本线作业；不是把正常退出当成能力依据，以上均按实际绑定、状态与像素检查。未做性能优化／大规模验证，不因余额存在继续运行。

## 归档与回退

[Charger对象档案](../../assets/appearance/objects/drawer_plug/charger/README.md)沿用PR #3对象路径，只引用现有参数与本轮证据。PR #3未合并时本分支不导入整套档案；后续合并需保留该对象的实际新状态，不覆盖其它对象资料。

关闭kwarg即可走原生路径。代码回退通过撤销本分支新增提交，不撤销Bob材质交付，不强推／合并main。本分支完成限定检查后交Dennis／leader审阅，不自行合并或开展其它物体。
