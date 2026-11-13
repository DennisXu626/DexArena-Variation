# 当前能力与验证边界

2026-11-13建仓基线继承已验收M2及续篇001；现已整合Charger材质、统一物体档案及A4／A5已验收接入。本轮仓库整合只做Git／CPU静态与哈希核对，**没有重跑仿真、渲染或训练**。

## Cabinet试点（继承M2及续篇001）

| 项目 | 已验收能力 | 限制 |
|---|---|---|
| 任务 | CabinetPouringPickBottle-Sharpa-v1、CabinetPouringUnscrewCap-Sharpa-v1 | 其它家族、其它手型未作variation验收 |
| 外观 | 原版＋Ocean／Citrus／Violet；真实标签替换、盖主体及非对称参照改色；明确选择和集合随机选择 | 不增加几何／UV；新方案需实际任务画面检查 |
| 表示 | 动态A、固定B、开口C与附着／自由盖同回合方案一致 | 工程触发切换的检查不是机器人真实完成阶段 |
| 位姿 | UnscrewCap原范围合法固定XY、原盘采样及原生初始化；最终有效B记录 | 仅identity朝向；不扩大范围；PickBottle保持柜内起点 |
| 并行 | 1／2／4环境分项检查；两个任务16环境关闭／联合开启，重复非连续局部reset和RGB流程 | 不是任意规模、长期压力或1024环境验收 |
| 隔离 | 未选环境的物理状态、材质、显示及三观测相机＋human画面保持 | 比较期间无物理步进、相机不变 |
| 默认／物理 | 关闭功能委托原生路径；默认状态、机器人、视觉／碰撞几何及物理配置对照保持 | 保留原生随机性；不承诺新增随机流逐样本等于原流 |

续篇根因：SAPIEN3.0的瓶／盖visibility变化使既有批量渲染组失效，即使reset最后恢复同一表示也会报错。任务层在真实可见性变化后，使用现有原生接口刷新渲染组并重新绑定原相机；不改共享核心，不重置全部环境，不改物理语义。

历史原始证据由维护者保管（M2首轮、continuation_001及validation_16）。向维护者申请状态／图像／清单即可复核，本仓库只保存精简来源和结论，不假装内部证据路径是可访问链接，不上传原始服务器日志或大量输出。

## Charger试点（已接受A1–A3及限定A4／A5）

Bob交付original／ivory_matte／navy_satin／copper_metal材质及单环境预览；本线完成PickCharger与InsertPlug各2env正式接入和A4／A5。四固定方案、指定集合随机复现、回合ID／版本记录、原生物理／初态一致性以及仅env1局部reset后的env0状态／材料／三路RGB＋human隔离均通过。实际生产测试提交38b8474，后续整合不改变其生产文件。

唯一参数源是[Charger catalog](../../tasks/assets/variation/drawer_plug/v1/catalog.json)，[对象档案](../../assets/appearance/objects/drawer_plug/charger/README.md)和[总索引](../../assets/appearance/README.md)只引用参数并同步状态；不是独立catalog。[用法和证据](CHARGER_A4_A5.md)限定两任务2env、原初态成功逻辑对照及无物理步进的像素比较；完整机器人任务成功、其它手型／规模、长期压力和A6未验证。

后续工作须另行提出PR并取得运行资源授权，不因本轮整合或既有余额扩大范围。全正式任务覆盖仍是最终目标，尚未实现；场景背景变化后置。
