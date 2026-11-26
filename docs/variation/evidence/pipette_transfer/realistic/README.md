# Pipette Transfer 真实版验收

## PR #37 R2 公开 reset 复验

Server 3 作业 `143432` 用同一检查器核验审阅时的提交 `1e0a4a0`、修复提交 `03ef33a`，以及修复提交与 `main@8629653` 的集成树。每种排列独立建场，从 original 开始，两行 CUDA 环境均使用 seed 7。两次 reset 之间零步进。每轮依次保留 reset 返回的任务 RGB、下一次 get_obs 的任务 RGB 和 human 相机 RGB，同时保存各自的分割附件。最后才下载材质贴图。[Linux 逐行结果与原始数据包位置](r2/linux.json)

| 任务 | 首帧、下一帧中可区分玉绿和珊瑚的底板像素（env0 / env1） | human 相机（env0 / env1） |
|---|---:|---:|
| AspirateLiquid | 224 / 228 | 503 / 515 |
| DispenseLiquid | 390 / 370 | 880 / 847 |

表中两种颜色在可见底板的每个像素都有差异。冻结旧版的 AspirateLiquid 在同一遮罩内两色完全相同，检查器当场报错。修复后，`jade/jade`、`coral/coral`、`jade/coral`、`coral/jade` 四种排列的每一行都匹配直接以对应候选建场的独立参照。[AspirateLiquid 修复前后同位置裁切](r2/AspirateLiquid.png)

Server 3 上 `xkl` 可读的原始数据包为 `/var/tmp/dexarena-pr37-r2-xkl-20261126.EQYTzb/plate-reset-rgb-segmentation.tar.gz`。将其解压至新目录后，在该目录中用带 NumPy 和 Pillow 的 Python 复算。

```sh
sha256sum -c SHA256SUMS --quiet
python audit_raw.py AspirateLiquid head/AspirateLiquid audit --old before/AspirateLiquid
python audit_raw.py DispenseLiquid head/DispenseLiquid audit
```

与冻结旧版的固定候选相比，单级贴图采样改变了底板标识的细节。AspirateLiquid 底板内最大通道差为 39，底板外差异为零。original 两行的任务相机和 human 相机均逐字节复现旧版。[Windows 双环境复算](r2/windows-cuda.json)

Windows 原生 CPU 接口和 26 轮动态回归也在修复提交上通过。1,560 个控制步、31,200 个物理子步的逐帧状态和回报与原生轨迹一致。[CPU 回放回执](r2/windows-cpu.json)

Server 3 的完整双环境验收覆盖 original 和十套候选，共复算 990 组外观配对、130 次选中状态读回及 20 次恢复。光学补测复算 112 组相机对照，其中 AspirateLiquid 有 5 组承托盘没有共同可见像素。底板使用本任务的实际分割编号，AspirateLiquid 为 112，DispenseLiquid 为 120。[标准 CUDA 与光学回执](r2/linux-standard.json)

## 首次提交的验收

以下结果对应采集提交 `5cf3c6e7683994ff0fa628aa320434ecb10ab2a5`。全部采集覆盖 AspirateLiquid 与 DispenseLiquid 的 original 和十套候选。

| 检查 | 结果 |
|---|---|
| Windows 双环境标准 CUDA | 990 组逐对象配对通过，最弱一组有 71 个遮罩像素的最大通道差达到 8。130 次选中状态读回通过。20 次固定候选恢复 original 以及双向局部重置的未选环境 RGB 差均为零。[原始数据复算](windows-cuda.json) |
| Windows CPU 接口与动态 | 26 轮合计 1,560 控制步、31,200 物理子步。回放逐帧状态及动作，全部候选复现原生轨迹。[原始数据复算](windows-cpu.json) |
| Server 3 双环境标准 CUDA | 作业 `135568` 在 `lyg0295` 的 A800 上以受控 Linux SDK 运行。990 组逐对象配对、130 次选中状态读回、20 次固定候选精确恢复均通过，局部重置隔离通过。[任务与原生 SDK 回执](linux-cuda-optical.json) |
| Server 3 光学补测 | 独立重算 56 次场景构造及 112 组相机深度对照。AspirateLiquid 有 5 组承托盘受遮挡，其余共同可见像素的最大深度偏置误差为 `2.66e-8`。[原始数据复算](linux-cuda-optical.json) |

任务图取自同一批原生 human 相机帧，组内使用相同裁切位置。[AspirateLiquid](AspirateLiquid.png) · [DispenseLiquid](DispenseLiquid.png) · [支架底板近景](StandPlate.png)

底板近景使用 DispenseLiquid 的 env0，每套均保留原任务中的光照、位置和相机。在同一底板分割遮罩内，十一项渲染的平均 RGB 均不同。壳体、导向件与半透明玻璃在原任务拍摄视角下另按各自的遮罩对照。
