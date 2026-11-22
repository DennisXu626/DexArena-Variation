param(
    [Parameter(Mandatory)][string]$Batch,
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$SapienRoot,
    [Parameter(Mandatory)][string]$Artifact,
    [Parameter(Mandatory)][string]$PhysxGpuDir,
    [string]$GpuLock,
    [ValidateSet('OpenLaptop', 'TypeKeys', 'ClickMouse', 'CPUInterface', 'CPUDynamics')]
    [string[]]$Runs = @('OpenLaptop', 'TypeKeys', 'ClickMouse', 'CPUInterface', 'CPUDynamics')
)

$ErrorActionPreference = 'Stop'
$sdk = @('--sapien-root', $SapienRoot, '--artifact', $Artifact, '--physx-gpu-dir', $PhysxGpuDir)
$runtime = @('-B', 'tools/variation/sapien_sdk/run_task_check.py', '--repo-root', '.', '--checker',
    'tools/variation/check_office_devices_runtime.py', '--approved-runtime') + $sdk
$null = New-Item -ItemType Directory -Force -Path $Batch
foreach ($run in $Runs) {
    switch ($run) {
        'CPUDynamics' {
            $output = "$Batch/cpu_dynamics"
            $command = @('-B', 'tools/variation/check_office_devices_dynamics.py', '--steps', '60', '--seed', '7') + $sdk
        }
        'CPUInterface' {
            $output = "$Batch/cpu_interface"
            $command = $runtime + @('--sim-backend', 'physx_cpu')
        }
        default {
            $output = "${Batch}/${run}_cuda"
            $command = $runtime + @('--sim-backend', 'physx_cuda', '--experimental-windows-cuda',
                '--gpu-memory-profile', 'two_env', '--task', $run)
        }
    }
    $command += @('--output', $output)
    $existing = @($output, "$output.process.json", "$output.stdout.log", "$output.stderr.log") |
        Where-Object { Test-Path -LiteralPath $_ }
    if ($existing) { throw "Use a new output prefix for $run" }
    $started = [DateTime]::UtcNow.ToString('o')
    if ($GpuLock) {
        & $GpuLock -Executable $Python -ArgumentList $command 1> "$output.stdout.log" 2> "$output.stderr.log"
    } else {
        & $Python @command 1> "$output.stdout.log" 2> "$output.stderr.log"
    }
    $code = $LASTEXITCODE
    @{
        command = $command
        executable = $Python
        started_utc = $started
        ended_utc = [DateTime]::UtcNow.ToString('o')
        exit_code = $code
        stdout_sha256 = (Get-FileHash -LiteralPath "$output.stdout.log").Hash.ToLowerInvariant()
        stderr_sha256 = (Get-FileHash -LiteralPath "$output.stderr.log").Hash.ToLowerInvariant()
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath "$output.process.json" -Encoding utf8
    if ($code -ne 0) { throw "$run failed with exit code $code. See $output.stderr.log" }
    Write-Output "$run passed"
}
