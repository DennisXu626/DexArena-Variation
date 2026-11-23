# PR19-R2 作者返修

受审 head 9141ca3d86c81d82bd2e25ee083b396359c0091f；已将审核 main 58b54623308ad736f765a8bbccefc74e344f2a3c 合入工作树（未提交）。

- R2-1：真实 b22 BaseEnv 在恢复 scene 全选掩码后调用 controller.reset，因此共享控制器内部索引不足以隔离。Juice 公共 reset 递归保存未选行控制器 tensor buffers，在 get_info/观测前及 finally 恢复；显式局部 seed 在父 reset 任何写入前拒绝。已有阶段作用域保持。
- 由 AUTHOR 探针派生 check_juice_r2_isolation_cpu.py，增加 seed 拒绝、未选目标/RNG 与实际返回观测目标断言。加载真实 b22 reset/RNG、当前 main 控制器，两个方向共4组通过：目标 .25 保持，随机下一值一致。seed 用例预期 ValueError，故不直接以旧探针异常退出作为失败。
- R2-2：解决 assets/appearance/README.md 和 runtime_mapping.json 两处冲突，保留 main 已有家族和 Juice 四候选；CSV 自动合并。42 对象统计 accepted_pilot14 / pending_adaptation17 / no_visual3 / not_loaded1 / implemented_pending_review3 / external_pending4。无未解决索引。

原 R1 10 项 CPU 测试继续通过；check_static.py 和 check_appearance_archive.py 均通过，结果见 evidence/juice_preparation/r2_checks.json。反例回归见 r2_isolation.json。

范围 original + variant_1 + variant_2。未修改共享控制器、未运行服务器/GPU、未提交推送或合并 PR。真实双环境 reset 和编号配色仍由独立执行层验证。
