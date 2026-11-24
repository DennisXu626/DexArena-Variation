# Pipette Transfer 扩容验收

Server 3 的作业 `123819` 在受控 Linux SAPIEN `3.0.3+dexarena.gpu1.linux1` 上运行 AspirateLiquid 与 DispenseLiquid 的标准双环境 CUDA RGB，并分别采集任务深度。 [采集与发布源码身份](capture.json)记录采集提交、发布运行提交、两者实际运行路径的 Git 对照及附图 SHA-256。[原始产物独立复核](review.json)包含阶段读回、深度可见性、逐对象配对、恢复与隔离的逐项记录。

- [两任务、两环境、十一套固定外观](overview.png)
- [同一批相机帧的对象近景](closeups.png)
- [DispenseLiquid 原版](DispenseLiquid/original_human_env0.png) · [variant_3](DispenseLiquid/variant_3_human_env0.png) · [variant_10](DispenseLiquid/variant_10_human_env0.png)
- AspirateLiquid 局部 reset [env0 保持](AspirateLiquid/local_variant_3_variant_4_1_base_camera_env0.png) · [env1 恢复](AspirateLiquid/local_variant_3_variant_4_1_base_camera_env1.png)
- DispenseLiquid 局部 reset [env0 保持](DispenseLiquid/local_variant_3_variant_4_1_base_camera_env0.png) · [env1 恢复](DispenseLiquid/local_variant_3_variant_4_1_base_camera_env1.png)

固定原图来自 `human` 相机的 env0。局部 reset 前后使用 `base_camera`，只 reset env1；左图是 reset 前，右图是 reset 后。图像保留原始 PNG 字节，概览和近景由同次采集的任务相机帧排版。

本机 Windows 复验另见[双环境 CUDA 原始数据复核](windows-gpu-review.json)和[CPU 动态复核](windows-cpu-dynamics.json)。

[配置与命令](../../../PIPETTE_APPEARANCE.md)
