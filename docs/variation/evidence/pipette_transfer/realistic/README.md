# Pipette Transfer 真实版验收

采集提交为 `5cf3c6e7683994ff0fa628aa320434ecb10ab2a5`。全部采集覆盖 AspirateLiquid 与 DispenseLiquid 的 original 和十套候选。

| 检查 | 结果 |
|---|---|
| Windows 双环境标准 CUDA | 990 组逐对象配对通过，最弱一组有 71 个遮罩像素的最大通道差达到 8。130 次选中状态读回通过。20 次固定候选恢复 original 以及双向局部重置的未选环境 RGB 差均为零。[原始数据复算](windows-cuda.json) |
| Windows CPU 接口与动态 | 26 轮合计 1,560 控制步、31,200 物理子步。回放逐帧状态及动作，全部候选复现原生轨迹。[原始数据复算](windows-cpu.json) |
| Server 3 双环境标准 CUDA | 作业 `135568` 在 `lyg0295` 的 A800 上以受控 Linux SDK 运行。990 组逐对象配对、130 次选中状态读回、20 次固定候选精确恢复均通过，局部重置隔离通过。[任务与原生 SDK 回执](linux-cuda-optical.json) |
| Server 3 光学补测 | 独立重算 56 次场景构造及 112 组相机深度对照。AspirateLiquid 有 5 组承托盘受遮挡，其余共同可见像素的最大深度偏置误差为 `2.66e-8`。[原始数据复算](linux-cuda-optical.json) |

任务图取自同一批原生 human 相机帧，组内使用相同裁切位置。[AspirateLiquid](AspirateLiquid.png) · [DispenseLiquid](DispenseLiquid.png) · [支架底板近景](StandPlate.png)

底板近景使用 DispenseLiquid 的 env0，每套均保留原任务中的光照、位置和相机。在同一底板分割遮罩内，十一项渲染的平均 RGB 均不同。壳体、导向件与半透明玻璃在原任务拍摄视角下另按各自的遮罩对照。
