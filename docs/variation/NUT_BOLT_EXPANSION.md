# Nut & Bolt 外观扩容

本页记录 v2 扩容与当时的验收。当前外观见 [Nut & Bolt 真实版](NUT_BOLT_REALISTIC.md)。

bolt 和 nut 各追加 `variant_3`–`variant_10`。每个对象共有原版加十套候选。螺栓改 shaft 和 head，保留 tip 和 thread。螺母 free／threaded 共用同一个方案，保留原生切换和参照面绑定。三个任务的几何、碰撞、物理和相机采用原任务定义。

饰面以琥珀、朱红、青柠、水蓝、紫、石墨、冰银和品红为主。完整名称和数值分别见 [bolt catalog](../../assets/appearance/objects/nut_bolt/bolt/variants/v1/catalog.json) 与 [nut catalog](../../assets/appearance/objects/nut_bolt/nut/variants/v1/catalog.json)。[运行索引](../../tasks/assets/variation/nut_bolt/v1/catalog.json) 枚举方案，[双环境配置示例](../../examples/variation/nut_bolt/expansion.json) 演示按环境覆盖。

## 验证

CPU 契约测试通过三项短任务的公开 `reset` 验证全部方案。对每个 ID，先用该合法 ID 加随机列表末项错字检查拒绝，再用该 ID 单独检查合法转发。拒绝时任务和外观 RNG、状态、锁和材质均无变化。

Windows v7 [成功路径运行档案](../../assets/appearance/objects/nut_bolt/previews/runtime_expansion_v2/summary.json)对应索引记录的采集源码与 SDK 身份。CPU 接口覆盖三个短任务。动态复算对每任务的两次关闭对照、original 和十套候选逐步比较，合计 2,340 控制步、46,800 物理步，状态、控制目标、奖励和任务结果精确一致。标准双环境 CUDA 共 168 次选中读回、6 控制步和 120 物理步。所有候选均恢复到逐值相同的 original，双向局部 reset 的未选状态和 RGB 精确相等。

| 任务 | 固定原生见证相机 | 两环境共对照 | 相差至少 8 的最少像素 |
| --- | --- | ---: | ---: |
| PickBolt | base camera | 110 | 50 |
| SeatNut | wrist camera | 110 | 68 |
| TurnNut | human | 110 | 550 |

[归档索引](../../assets/appearance/objects/nut_bolt/previews/runtime_expansion_v2/summary.json) 提供每任务 11 套见证图、逐对数据、双向局部 reset 与 SeatNut 阶段切换图，共 50 张原始 PNG。固定图为原版在左、所示方案在右。归档另含同一 SDK 的 160 步原生探针，六轴锁定和解锁、索引恢复及真实接触均通过。

扩容代码的 [Windows 复验](evidence/nut_bolt/windows_expansion_review.json) 重新执行三个任务的 `physx_cpu` 动态与标准双环境 CUDA。CPU 无图像采集，逐状态复算通过。CUDA 复算原图、材质、局部 reset 和原版恢复。新回执保留本次运行的真实源码、SDK 和原始文件摘要。

## Linux CUDA 复验

Server 3（`lyg0295`）作业 `123850` 使用双环境标准 ManiSkill CUDA RGB 和私有 SAPIEN `3.0.3+dexarena.gpu1.linuxnut1`。三任务共 168 次选中状态读回、6 控制步、120 物理子步和 330 组候选对照。四路原相机参加双向局部 reset、原版恢复与未选环境精确隔离。SeatNut 验证了原生阶段切换，独立探针验证了双场景光栅和 160 步六轴锁定及接触。

[Linux 复算摘要](../../assets/appearance/objects/nut_bolt/previews/runtime_expansion_linux/summary.json) 保留实际采集提交和 SDK 身份。[源码比对](../../assets/appearance/objects/nut_bolt/previews/runtime_expansion_linux/source_equivalence.json) 核对采集用 206 个文件的 SHA-256。[原相机画面与图像清单](../../assets/appearance/objects/nut_bolt/previews/runtime_expansion_linux/figures.json) 包含三个任务的候选图和 PickBolt 的两种隔离方向。

在获准的单卡窗口使用 [Nut 私有 Linux SDK](../../tools/variation/sapien_sdk/native_lock/recipe-linux/README.md) 与项目依赖的 CPython 3.10 环境。先按配方串行执行 lock 和 raster，再从仓库根运行如下任务。将 `sdk_root` 和 `run` 设为私有 SDK 与本次的新输出根，`artifact_sha256` 设为审核过的 SHA-256。

```bash
repo=$(pwd)
common="$repo/tools/variation/sapien_sdk"
artifact="$sdk_root/artifact.json"
wheel=$(python3.10 -c 'import json,sys; print(json.load(open(sys.argv[1]))["wheel"])' "$artifact")
test "$(sha256sum "$artifact" | cut -d ' ' -f 1)" = "$artifact_sha256" || exit $?
mkdir -- "$run" || exit $?

for task in PickBolt SeatNut TurnNut; do
  python3.10 -B "$common/run_linux_check.py" --checker nut --repo-root "$repo" \
    --artifact "$artifact" --wheel "$sdk_root/$wheel" --physx-gpu-dir "$sdk_root/physx-runtime" \
    --approved-runtime --two-env-memory --task "$task" --output "$run/$task" || exit $?
done
```

## 验证命令

从仓库根运行静态检查与公开 reset 契约。

```powershell
python -B tools/variation/check_static.py
python -B tools/variation/check_appearance_archive.py
python -B tools/variation/check_nut_bolt_appearance.py --static
python -B -m unittest discover -s tests -p 'test_nut*.py'
```

从当前仓库根目录使用锁定 CPython 和 [Windows v7 SDK](../../tools/variation/sapien_sdk/native_lock/README.md)。示例中 `$run` 是新目录，GPU 检查串行执行。本地协调工作区用可选共享锁包装同一命令，独立复现直接运行仓库内的 monitor 和 launcher。

```powershell
$py = 'C:/path/to/python.exe'
$sdk = 'C:/path/to/verified-private-v7'
$repo = (Get-Location).Path
$run = Join-Path $repo '.local/nut_bolt/expansion-v2-reproduction'
$sdkTools = Join-Path $repo 'tools/variation/sapien_sdk/native_lock'
$launcher = "$sdkTools/tools/run_task_check.py"
$receipt = (Get-FileHash "$sdk/artifact.json" -Algorithm SHA256).Hash.ToLower()
$sdkArgs = @('--sapien-root', "$sdk/runtime", '--artifact', "$sdk/artifact.json", '--artifact-sha256', $receipt, '--physx-gpu-dir', "$sdk/physx-runtime")
$checker = @('--repo-root', $repo, '--checker', 'tools/variation/check_nut_bolt_runtime.py') + $sdkArgs
New-Item -ItemType Directory -Path $run -ErrorAction Stop | Out-Null

& $py -B tools/variation/check_nut_bolt_appearance.py --static --output "$run/static.json"
if ($LASTEXITCODE) { throw 'Static appearance checks failed' }
function Invoke-NutCpuEvidence($name, [string[]]$command) {
    & $py @command > "$run/$name.stdout.txt" 2> "$run/$name.stderr.txt"
    $code = $LASTEXITCODE
    @{
        returncode = $code
        stdout_sha256 = (Get-FileHash "$run/$name.stdout.txt").Hash.ToLower()
        stderr_sha256 = (Get-FileHash "$run/$name.stderr.txt").Hash.ToLower()
    } | ConvertTo-Json | Set-Content -LiteralPath "$run/$name.process.json" -Encoding utf8
    if ($code) { throw "Failed: $name" }
}
Invoke-NutCpuEvidence 'cpu-interface' (@('-B', $launcher) + $checker + @('--approved-runtime', '--sim-backend', 'physx_cpu', '--output', "$run/cpu-interface"))
Invoke-NutCpuEvidence 'cpu-dynamics' (@('-B', 'tools/variation/check_nut_bolt_dynamics.py') + $sdkArgs + @('--approved-runtime', '--steps', '60', '--seed', '7', '--output', "$run/cpu-dynamics"))

$cases = @(@('PickBolt','7','base_camera'), @('SeatNut','1','wrist_camera'), @('TurnNut','26','human'))
foreach ($case in $cases) {
    $task, $seed, $camera = $case
    $output = "$run/gpu-$task"
    $child = @($py, '-B', $launcher) + $checker + @('--approved-runtime', '--sim-backend', 'physx_cuda', '--experimental-windows-cuda', '--gpu-memory-profile', 'two_env', '--task', $task, '--seed', $seed, '--visibility-camera', $camera, '--output', $output)
    $monitor = @('-B', "$sdkTools/probes/monitor_gpu_window.py", '--output', "$output-monitor", '--delta-mib', '1792', '--timeout-s', '900', '--')
    $gpuArgs = $monitor + $child
    & $py @gpuArgs
    if ($LASTEXITCODE) { throw "Failed: $task" }
}
```

CPU 动态每任务 13 组，各 60 个控制步。两组关闭外观，另 11 组逐套采用相同动作。正式 CUDA 检查使用四个原生相机，固定种子比较全部方案对，并逐套恢复原版。每个方案对在两环境的见证相机分别至少有 12 个像素的某个 8 位 RGB 通道相差 8 或以上。原版恢复、重复原生帧和局部 reset 未选环境要求精确相等。SeatNut 还采集原生阶段交换的首帧、重复帧和局部复原。

SDK 探针也串行执行，使用同一个解释器和 receipt。

```powershell
$probes = @(@('sdk-raster','tools/probe_batched_visibility.py'), @('sdk-native-lock','probes/check_runtime_lock.py'))
foreach ($probe in $probes) {
    $name, $script = $probe
    $output = "$run/$name"
    $child = @($py, '-B', "$sdkTools/tools/launch_native_lock.py", '--sdk-root', $sdk, '--python', $py, '--repo-root', $repo, '--cwd', $repo, '--artifact-sha256', $receipt, "$sdkTools/$script", '--', '--output', $output)
    $monitor = @('-B', "$sdkTools/probes/monitor_gpu_window.py", '--output', "$output-monitor", '--delta-mib', '1792', '--timeout-s', '240', '--')
    $gpuArgs = $monitor + $child
    & $py @gpuArgs
    if ($LASTEXITCODE) { throw "Failed: $name" }
}
& $py -B tools/variation/compact_nut_bolt_sdk_probes.py --repo $repo --sdk-root $sdk --raster "$run/sdk-raster" --raster-monitor "$run/sdk-raster-monitor" --native-lock "$run/sdk-native-lock" --native-lock-monitor "$run/sdk-native-lock-monitor" --monitor-tool "$sdkTools/probes/monitor_gpu_window.py" --output "$run/sdk_probe_checks.json"
if ($LASTEXITCODE) { throw 'SDK probe export failed' }
```

[导出器](../../tools/variation/compact_nut_expansion.py) 从标准 CUDA 图像和原始状态、CPU 轨迹以及 SDK 探针摘要复算。它要求原始批次与当前输入源码一致，复现使用新采集批次和新输出路径。

```powershell
& $py -B tools/variation/compact_nut_expansion.py --run $run --sdk-root $sdk --output "$run/review-export"
```

验收范围为 PickBolt、SeatNut 和 TurnNut 的 Windows／Linux 短任务。Long 和完整机器人策略成功留待验证。
