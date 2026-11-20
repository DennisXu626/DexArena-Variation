# Linux：Furniture Assembly 双环境局部 reset

[Issue #18](https://github.com/DennisXu626/DexArena-Variation/issues/18) 的 Server 3 预检加载了原版 SAPIEN 3.0.3。该构建不提供按选中物理对象索引写回的原生接口，因而不能用于 Furniture 的双环境局部 reset。使用补丁构建私有 Linux SDK，保留任务的原生能力检查和索引边界。

Linux 配方锁定 SAPIEN 3.0.3 的源提交、PhysX 5.3.1 主机库及 GPU 动态库。源码补丁修正六条按索引写回的原生路径，并从同一原生模块导出 `indexed_gpu_apply_patch_version() == 1`。方案 ID、材质和任务逻辑保持原样。

## 构建与只读预检

在 Linux x86_64 个人作业目录运行。[Linux 构建锁](../../tools/variation/sapien_sdk/lock_linux.json) 记录了上游工具链镜像。镜像默认 Python 版本不用于本构建，显式选 `/opt/python/cp310-cp310/bin/python`。原生构建须使用 CUDA 11.8 的真实 `CUDA_PATH` 和支持 `--internal` 的上游 auditwheel。任务另用具备项目依赖的 CPython 3.10，例如 Server 3 已经批准使用的项目环境；从私有路径加载 wheel，无须安装到共享环境。GPU 启动器核对实际映射的系统 `libcuda.so.1`，在本次输出目录为该进程提供 SAPIEN 要求的 `libcuda.so` 别名，拒绝 CUDA stub。源码、wheel、依赖、运行输出和日志留在私有目录，仓库只保存复现配置。

```bash
set -euo pipefail
root=$(pwd)
tool="$root/tools/variation/sapien_sdk"
work="$HOME/dexarena-sapien-linux-private"
build_python=/opt/python/cp310-cp310/bin/python
"$build_python" -B "$tool/build_linux.py" prepare --work-dir "$work"
"$build_python" -B "$tool/build_linux.py" build --work-dir "$work" --jobs 2
# 接下来在项目任务环境内运行，以实际的 CPython 3.10 路径填入 task_python。
task_python=/path/to/team-python3.10
wheel=$("$task_python" -c 'import json,sys; print(json.load(open(sys.argv[1]))["wheel"])' "$work/artifact.json")
CUDA_VISIBLE_DEVICES= "$task_python" -B "$tool/run_linux_check.py" --repo-root "$root" \
  --wheel "$work/$wheel" --artifact "$work/artifact.json" \
  --physx-gpu-dir "$work/physx-runtime" --output "$work/preflight" --probe-only
```

`prepared_linux.json` 记录准备后的源码和依赖；`artifact.json` 记录确切 wheel、ELF、源码、补丁和 PhysX 的 SHA-256。预检只加载轮子、核对实际原生绑定及能力并写 `preflight/private_sdk.json`。标记为 1 仅证明加载通过，不证明 GPU 隔离。若找不到能力、原生路径或哈希不符，立即停止。

## 三项任务的 GPU 验收

仅在获得项目的本轮 GPU 资源授权后，在同一个受控分配内串行运行。三项均使用标准 ManiSkill CUDA RGB、两个环境、原相机，不使用 Windows 诊断路径。给每项验收保留独立新目录。

```bash
for task in LayFlatPanel InsertRail FastenScrew; do
  "$task_python" -B "$tool/run_linux_check.py" --repo-root "$root" \
    --wheel "$work/$wheel" --artifact "$work/artifact.json" \
    --physx-gpu-dir "$work/physx-runtime" --output "$work/$task" \
    --approved-runtime --task "$task"
done
"$task_python" -B tools/variation/review_furniture_linux_capture.py \
  --artifact "$work/artifact.json" \
  --run "$work/LayFlatPanel" --run "$work/InsertRail" --run "$work/FastenScrew" \
  --output "$work/review"
```

复核读取采集的状态张量和原始相机 PNG，要求实际加载的 SDK/PhysX、原生 CUDA 运行和当前源码一致。检查三项任务各自的两个局部重置方向、未选环境保持和选中环境恢复。索引列出 48 格「请求 ID → 回合记录的实际 ID → 对象材质 → 原相机图像」，其中 `variant_4` 是琥珀橙、`variant_8` 是鸢尾紫。审阅以本轮新采集为准。

Linux 启动器在验证相机 RGB 后读取进程中的 Vulkan 动态库路径和哈希。场景关闭后，仍校验实际加载的 SAPIEN、CUDA 和 PhysX 身份。Vulkan 在关闭场景时正常卸载也能由取帧时的回执复核。

Server 3 的作者复验记录了三个短任务的双环境结果、48 格新增配色和双向局部 reset。运行使用的提交、SDK、已加载原生库及原始证据哈希保留在报告中。[实际作业摘要](evidence/furniture_assembly/linux_reset_issue18/server3_author_validation.json) · [原相机画面索引](evidence/furniture_assembly/linux_reset_issue18/INDEX.md) · [复算报告](evidence/furniture_assembly/linux_reset_issue18/review.json)

历史 Windows 档案保留原来的运行身份。Linux 长任务和完整机器人策略成功仍待验证。
