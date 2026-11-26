# PR40-R1 基线整合与独立验证

2026-11-26，受审 PR40 `1bca422f9e561d847233a63d1f572cfe4590ab25` 整合正式 main `6e3467b537bd67de3aeadb6758dc46d54170b96f`，其中包含已接受 PR19 squash `d02df83ded4bbf7375531313ff2977572b3e8454`。

## 冲突与差异审查

逐项检查了五处 add/add：历史说明追加八套扩展与 R1 状态；catalog 保留 original/1/2 并加入 3–10；appearance 仅扩展苹果算法开关；appearance_colors 默认保持旧算法；preview 复用生产改色函数并按 ID 标图、三列换行。当前 main 另产生 STATUS 内容冲突，保留 main 已接受状态。README 自动合并结果相对 main 无差异。

六任务生产逻辑、reset_guard 与 main 一致，包括错误请求预校验、PressButton 计数/成功锁存及 Long 阶段隔离。ID 1/2 配方不变，新增 ID 3–10 保留全部颜色/粗糙度与 apple_match_target。没有更改物理、门槛、随机模式或验证容差。

[源码审查](evidence/juice_ten/pr40_r1/integration_audit.json)对照作业 138333 的15文件归档：无语义差异。catalog、生产代码、GPU checker 与旧运行内容保持一致；字节换行差异逐文件列出。已有 CPU checker 的图册断言从横排更新为三列换行，继续验证四个乱序 ID、标签与像素对应；移除结果中固定旧 head 的误导，改为读取当前 HEAD。

## 冻结与独立验证

以本整合提交冻结源码，服务器从 git archive 导出源码，并记录完整 SHA 与文件 SHA-256。使用独立新运行目录，复用已存在资产和 Python 环境，保留旧作业与证据。

计划完整复验六入口 original+1–10 的 A4、双向 A5、独立进程四步和临界 reset。新增覆盖矩阵为六入口×八个 ID×两个环境行（96项），报告真实绑定及不可见限制。独立盖与集成盖分别检查；颜色重点为苹果5橙/6蓝、底座5黄/7橙/10象牙白。另渲染可见苹果与底座/两类盖的近景；CPU物理预览不冒作双环境 CUDA 证据。

独立 Server 3 结果待运行后追加；历史138333不替代本次结论。范围仍限 Sharpa、2env、seed7、noise0；不宣称完整机器人成功率、其它手型/规模/seed、长期压力或性能。
