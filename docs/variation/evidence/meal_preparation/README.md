# Meal Preparation 运行证据

| 作业 | 验证范围 | 结构化结果 | 作业收据 |
| --- | --- | --- | --- |
| 86264 | 原版及两套外观的四任务单环境判定与物理对照，三个短任务的历史动作重放 | [逐步判定、重放、碰撞和关节摘要](job-86264-results.json) | [Monica 86264](https://pair-monica.ngrok.app/job/86264) |
| 86563 | 四任务各 2 环境局部 reset 隔离，备餐长任务启停成本 | [隔离和计时](job-86563-results.json) | [Monica 86563](https://pair-monica.ngrok.app/job/86563) |
| 86898 | 四任务各 2 环境，逐材质槽恢复原版及渲染复核 | [逐槽基线、恢复结果和 RGB 比对](job-86898-results.json) | [Monica 86898](https://pair-monica.ngrok.app/job/86898) |

Monica 收据入口需要团队登录。[运行身份](runs.json)记录各作业的 GPU、版本来源、核查范围内源码和配置的 SHA-256，以及原始报告哈希。86264 使用原任务代码加独立预览脚本。86563 使用 Meal 接入快照，核对的任务代码、catalog 和验证脚本与 PR 提交 `796ed7a` 的对应文件在统一 LF 换行后内容一致。86898 使用同一任务快照，只增加恢复验证脚本。仓库保留精简证据；原始报告和截图留在原运行目录。

## 86898 恢复原版

关闭 Variation 的环境作为独立原版基线。开启对照先令 env0 用方案一、env1 用方案二，只 reset env1 并指定 `original`，期间不推进物理。比较实际渲染组件每个槽的材质参数，以及贴图的像素哈希、尺寸、数据类型和色彩空间。对于源 RGB 贴图，比较时只补不透明的 alpha 通道。另比对原版和恢复后 env1 的 RGB，查验材质实际进入渲染。

| 任务 | 逐槽通过 | 两种原版的 RGB 差异 |
| --- | ---: | --- |
| 备餐开盒 | 12 / 12 | 所有相机逐值一致 |
| 放面包 | 22 / 22 | 所有相机逐值一致 |
| 舀番茄 | 22 / 22 | 所有相机逐值一致 |
| 备餐长任务 | 22 / 22 | 所有相机逐值一致 |

env0 的材质与方案记录保持一致。长任务的 env0 四路 RGB 逐值一致，几个短任务的单路最大差异为一个通道值 1/255。历史成本和动作重放沿用旧作业证据。

在获授权的 GPU 作业中，从仓库根目录执行以下命令。资产配置沿用 [Meal Appearance 使用说明](../../MEAL_APPEARANCE.md)。

```bash
python -B tools/variation/check_meal_restore_original.py --output outputs/meal_restore_original
```

