# Charger正式接入：A4／A5待运行验收

本分支依赖Bob [PR #2](https://github.com/DennisXu626/DexArena-Variation/pull/2)的已审阅提交5185f1dd61f2de88ab7d4ada7a2ef77f01e6b207。Bob交付部件／材质与单环境预览A1–A3；本分支负责正式接入和A4／A5，不要求Bob补做。当前只完成实现与CPU静态准备，**GPU预算待批准，A4／A5运行未测，不得称通过**。

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

当前没有运行结果或新RGB。原预览只证明Bob A1–A3，不能代替本次两个正式任务的A4／A5证据。后续运行前仍需确认已有Drawer资产及既有环境可用，不修改共享安装。

## 归档与回退

[Charger对象档案](../../assets/appearance/objects/drawer_plug/charger/README.md)沿用PR #3对象路径，只引用现有参数与预览。PR #3未合并时本分支不导入整套档案；后续合并需保留该对象的新状态，不能把未测写成通过。

关闭kwarg即可走原生路径。代码回退通过撤销本分支新增提交，不撤销Bob材质交付，不强推／合并main。原始CPU准备报告由维护者交付；本分支PR在运行批准并验证前保持草稿。
