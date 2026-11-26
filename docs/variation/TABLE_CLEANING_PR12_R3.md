# PR12-R3 作者返修

受审 head 7b572188880e1c667d2e7123d8bfe6ba550e20b5；已将审核 main 58b54623308ad736f765a8bbccefc74e344f2a3c 合入工作树（未提交）。

- R3-1：碎屑运动判定按每环境 elapsed step 缓存，同帧重复读取不消耗历史。选中行 reset 清除时间标记；正常下一步继续更新。AUTHOR 四组双向/外观开关反例返回 obs/info 的 n_in_pan 均保持 0，目标 0.25、阶段 [1,0]、局部 seed 拒绝保持。
- R3-2：arm 替身绑定真实环境的 scene；集成控制器隔离测试 4 项通过、0 errors。新增 obs/info 计数断言。旧负例与本轮正例分开。

CPU：isolation 4 项、reset 11 项、single-env 64 cases、preview 8 pairs 均通过。真实 ManiSkill 3.0.0b22 wheel AST 方法，CPU Torch 2.6.0；物理和渲染替身，不宣称真实 GPU 验收。

结果见 evidence/table_cleaning/r3_isolation.json、r3_author_probe.json、r3_checks.json。未修改共享控制器。未提交、推送或合并 PR；无服务器作业。
