# PR #13 · 运行收据 121613

**短检在首个全局随机状态断言停止，外观候选尚未运行，待 Dennis 查收，不合并。**

- 运行提交 `b4c944ad4f732c9c408cb1011c3388e3eb771314`；相对准备版 `f04fb18629514d0a39c77c8de5a8520bfb04e603` 仅变更短检脚本，以按物体分割记录目标像素并把 Charger 联动分开。生产文件及目录清单参数不变。
- 已取得 OpenDrawer 原生双环境的 reset、物理/材质快照和原相机 RGB。显式关闭外观的实例完成构建和 reset；检查器随后在比较全局 Torch RNG 摘要时停止，尚未到达关闭对照的状态、材质及 RGB 等值判据。
- [原生随机状态记录](OpenDrawer_native_native_rng.json)显示两次局部 reset 后 CUDA 摘要不同。安装版 ManiSkill 3.0.0b22 的显式 seed 初始化在 `torch.random.fork_rng()` 内进行，会恢复调用者状态；将 reset 后的全局摘要跨实例比较没有控制同一随机起点。失败记录未保留关闭实例的实际摘要，不能据此认定外观改变 RNG 或物理。建议后续仅修检查器采样口径，保留全部状态和 RGB 判据。
- [结构化结果](results.json) · [运行版本与哈希](manifest.json) · [调度与清理收据](receipt.json) · [唯一可供审图的原版视角（未调色或裁剪）](OpenDrawer_native_human_env0.png)。该视角为 OpenDrawer env0、seed 7、原任务 `render_camera`，仅显示原版木纹、层缝和把手；没有候选对照，也没有插座帧。
- PickCharger、InsertPlug、Long、候选恢复、随机复现、隔离和 Charger 兼容性均未运行。未测试完整任务、训练或 A6。作业 `FAILED 1:0`，单卡分配 14 秒，未重排、未重试，责任进程组已清空。
