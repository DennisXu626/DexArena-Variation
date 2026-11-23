# F4 恢复检查的复现方式

使用原 `DrawerPlugPickCharger-Sharpa-v1`、`physx_cuda` 双环境、`obs_mode="state"` 和 `reconfiguration_freq=0`。底层任务源码对应 `4b767e7`，F4 检查器对应 `f63db0c`。

只读覆盖时，Python 脚本参数使用生产源码下真实的检查器路径，矩阵仍从 `runtime_001` 读。以下变量由等待新审批的运行器按实际身份设置，应用输出指向新运行目录。

```bash
"$PYTHON" -B "$PRODUCTION_SOURCE/tools/variation/check_drawer_positions.py" \
  --samples "$PRIOR_RUNTIME/SAMPLES.csv" --output "$NEW_RUN/output" --placement-only
```

启动前从最终 argv 检查入口路径、辅助模块定位、矩阵哈希和 `--placement-only`。已验证的期望值见 [CPU 对照收据](CPU_ENTRYPOINT.json)。正式运行顺序为整批 seed 7，局部 reset 从 F4-0 的 seed 843/env1 开始，F4-1 为 seed 844/env0，直至 F4-8。每点执行原生判据后恢复目标充电器位姿及五项运动历史，比较两个环境的完整快照。未选环境的 reset 前后仍按严格等值比较。实际半径严格小于原 14 cm 才满足径向条件，圆周点和内缩 1 mm 的对照分别记录。

[九点请求与未运行状态](POINTS.csv) · [本轮报告](RESULTS.md)
