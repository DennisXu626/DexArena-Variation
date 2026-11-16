# PR8-R3：最新main整合与静态交付

Meal **限定技术验收通过，待整合/合并；集成状态见[PR8](https://github.com/DennisXu626/DexArena-Variation/pull/8)**。这是落实独立审验方的[PR8-R2查收结论](https://github.com/DennisXu626/DexArena-Variation/pull/8#pullrequestreview-5919739591)，执行层未提交批准、未合并PR，也未改变保护或权限。

## 本轮合并树

- 第一父提交（已查收PR head）：`4ede53ea0e4c631461b79e8116713bdc7cef11af`。
- 第二父提交（本轮main）：`be63bc8e6345c2fd761b98c68a1af145dc6e865b`。
- 共同基线：`acd6ba232b8da7a97fd313aa3df8a9f595fd55e0`。
- 操作为将上述main合入PR分支；未修改main、未强推、未重置作者工作。最终提交号及远端状态见PR8本轮收尾留言，避免提交内自引用。

冲突只在`assets/appearance/README.md`、`assets/appearance/runtime_mapping.json`、`docs/variation/STATUS.md`。保留Mouse限定验收与其全部入口，STATUS的Mouse第5节原文不变，Meal置第6节并引用已作出的技术验收结论。CSV自动合并后，只将Meal五行由`implemented_pending_review`改为`accepted_pilot`。

最终42对象状态从CSV计算：accepted_pilot=9、pending_adaptation=29、no_visual=3、not_loaded=1、implemented_pending_review=0、external_pending=0。同步对象索引、runtime_mapping、根README、五份Meal对象README和用法说明；运行参数不变。任务入口涉及四家族九入口：Cabinet两短任务、Charger两短任务、Mouse仅ClickMouse一短任务、Meal三短任务和一长任务入口；九个accepted对象不等于九个完整机器人任务成功。

## 最小核对与范围

[本轮静态记录](pr8-r3-static.json)包含父提交与生产文件双向基线hash、索引计数、范围断言和CPU检查结果。Meal生产文件、catalog与两验证脚本对4ede53e保持字节身份；Mouse生产、catalog、配置及已有证据对be63bc8保持字节身份。其它冲突解决差异仅为本执行单指定文档／索引，归档检查器逻辑不改。

历史[R1审阅](https://github.com/DennisXu626/DexArena-Variation/pull/8#pullrequestreview-5918176986)、[R2索引](PR8-R2.md)、原始结果、收据转录、事后资产清单和预览manifest保留原样。R1源码身份、76槽恢复original、四图、CPU选择逻辑及86563限定隔离已关闭，本轮不重跑。86264旧预览／回放不替代当前接入验收，历史追溯限制不消失。

技术接受范围为五对象original＋两候选、默认程序午餐盒、三个Sharpa短任务和一个Sharpa长任务入口、固定方案双环境局部reset及恢复original。随机方案仅CPU选择／记录逻辑；随机GPU、更多环境／手型、PartNet及完整机器人长任务成功仍未测。不新增功能、A6、训练或性能结论。

GPU新增0秒、新计算作业0次、仿真／训练／大型下载0。仅使用既有环境和隔离Git工作区，有限静态产物留D盘，无持续日志、后台重试或服务器清理。无需作者补充，无新增运行提案。最终合并由独立审验负责人执行，执行层完成本轮交付即停止。
