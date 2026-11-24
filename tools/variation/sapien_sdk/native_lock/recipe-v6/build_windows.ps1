param(
    [Parameter(Mandatory=$true)][string]$WorkDir,
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$PhysXStage,
    [string]$CMake = 'cmake',
    [string]$Ninja = 'ninja',
    [string]$VsInstall,
    [string]$GitBash,
    [ValidateRange(1,2)][int]$Jobs = 2
)
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'This build recipe is Windows-only.' }
$work = (Resolve-Path -LiteralPath $WorkDir).Path
$Python = (Resolve-Path -LiteralPath $Python).Path
$CMake = (Get-Command $CMake -ErrorAction Stop).Source
$Ninja = (Get-Command $Ninja -ErrorAction Stop).Source
$lock = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'lock.json') -Raw | ConvertFrom-Json
$vcvarsVersion = ($lock.tested_toolchain.toolset -split '\.')[0..1] -join '.'
$source = Join-Path $work 'source'
$cuda = Join-Path $work 'cuda'
$deps = Join-Path $work 'deps'
$install = Join-Path $work 'install'
$nativeBuild = Join-Path $work 'native-build'
$pythonBuild = Join-Path $work 'python-build'
$physxStage = (Resolve-Path -LiteralPath $PhysXStage).Path
foreach ($required in @('include/PxPhysicsAPI.h', 'bin/win.x86_64.vc143.mt/release/PhysX_static_64.lib')) {
    if (-not (Test-Path -LiteralPath (Join-Path $physxStage $required))) { throw "PhysXStage is missing $required" }
}

function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $Exe" }
}
function Forward([string]$Path) { $Path.Replace('\', '/') }
function Require-Version([string]$Name, [string]$Actual, [string]$Expected) {
    if ($Actual -ne $Expected) { throw "$Name version $Actual differs from locked $Expected; use the locked toolchain or review/update the lock and receipt." }
}
Invoke-Checked $Python @((Join-Path $PSScriptRoot 'prepare.py'), '--verify-only')
Invoke-Checked $Python @((Join-Path $PSScriptRoot 'prepare.py'), '--verify-work-dir', $work)
$pythonInfo = & $Python -c 'import platform,json,struct; from importlib.metadata import version; print(json.dumps(dict(python=platform.python_version(),setuptools=version("setuptools"),wheel=version("wheel"),pointer_bytes=struct.calcsize("P"))))'
if ($LASTEXITCODE -ne 0) { throw 'Python build-package query failed.' }
$pythonInfo = $pythonInfo | ConvertFrom-Json
Require-Version 'Python' $pythonInfo.python $lock.tested_toolchain.python
Require-Version 'setuptools' $pythonInfo.setuptools $lock.reference_packages.setuptools
Require-Version 'wheel' $pythonInfo.wheel $lock.reference_packages.wheel
if ($pythonInfo.pointer_bytes -ne 8) { throw 'A 64-bit Python interpreter is required.' }
$cmakeVersion = (& $CMake --version | Select-Object -First 1) -replace '^cmake version ', ''
$ninjaVersion = & $Ninja --version
Require-Version 'CMake' $cmakeVersion $lock.tested_toolchain.cmake
Require-Version 'Ninja' $ninjaVersion $lock.tested_toolchain.ninja
if (-not $VsInstall) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    $VsInstall = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
}
if (-not $VsInstall) { throw 'vswhere did not report a C++ toolset; pass -VsInstall with the existing Visual Studio installation.' }
$vsdev = Join-Path $VsInstall 'Common7\Tools\VsDevCmd.bat'
if (-not (Test-Path -LiteralPath $vsdev)) { throw 'MSVC x64 development tools are required.' }
# Only this process receives the compiler environment. No registry/system/conda edits.
$envHelper = Join-Path $work 'compiler_env.cmd'
[IO.File]::WriteAllText($envHelper, "@echo off`r`ncall `"$vsdev`" -host_arch=x64 -arch=x64 -vcvars_ver=$vcvarsVersion >nul`r`nif errorlevel 1 exit /b %errorlevel%`r`nset`r`n")
# Pass cmd's command line directly; PowerShell 7 native-argument quoting differs.
$start = [Diagnostics.ProcessStartInfo]::new($env:ComSpec, ('/d /c call "{0}"' -f $envHelper))
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardOutput = $true
$start.RedirectStandardError = $true
$process = [Diagnostics.Process]::Start($start)
$environment = $process.StandardOutput.ReadToEnd() -split '\r?\n'
$envError = $process.StandardError.ReadToEnd()
$process.WaitForExit()
if ($process.ExitCode -ne 0) { throw "VsDevCmd failed: $envError" }
foreach ($line in $environment) {
    if ($line -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process') }
}
# Process-private build temporary files, after importing the VS environment.
$temporaryDirectory = Join-Path $work 'tmp'
New-Item -ItemType Directory -Force -Path $temporaryDirectory | Out-Null
$env:TEMP = $temporaryDirectory
$env:TMP = $temporaryDirectory
Require-Version 'MSVC toolset' $env:VCToolsVersion.TrimEnd('\') $lock.tested_toolchain.toolset
$compilerFileVersion = (Get-Item -LiteralPath (Join-Path $env:VCToolsInstallDir 'bin\Hostx64\x64\cl.exe')).VersionInfo.FileVersion
Require-Version 'MSVC compiler' $compilerFileVersion ($lock.tested_toolchain.msvc + '.0')
if (-not $GitBash) {
    $gitExe = (Get-Command git.exe -ErrorAction Stop).Source
    $gitRoot = Split-Path (Split-Path $gitExe)
    $GitBash = Join-Path $gitRoot 'bin\bash.exe'
}
if (-not (Test-Path -LiteralPath $GitBash)) { throw 'Pass -GitBash with Git for Windows bin/bash.exe; do not use WSL bash.' }

# CUDA 12.4 with the tested newer MSVC needs an explicit compatibility flag.
# A task-private host layout supplies vcvarsall when an installed toolset lacks it.
$hostRoot = Join-Path $work 'msvc-host'
$hostBin = Join-Path $hostRoot "VC\Tools\MSVC\$($env:VCToolsVersion.TrimEnd('\'))\bin\Hostx64\x64"
New-Item -ItemType Directory -Force -Path (Split-Path $hostBin) | Out-Null
if (-not (Test-Path -LiteralPath $hostBin)) {
    New-Item -ItemType Junction -Path $hostBin -Target (Join-Path $env:VCToolsInstallDir 'bin\Hostx64\x64') | Out-Null
}
$vcvars = Join-Path $hostRoot 'VC\Auxiliary\Build'
New-Item -ItemType Directory -Force -Path $vcvars | Out-Null
[IO.File]::WriteAllText((Join-Path $vcvars 'vcvarsall.bat'), "@echo off`r`ncall `"$vsdev`" -host_arch=x64 -arch=x64 -vcvars_ver=$vcvarsVersion`r`n")
$env:PATH = "$hostBin;$(Split-Path $CMake);$(Split-Path $Ninja);$cuda\bin;$env:PATH"
$env:CUDA_PATH = $cuda
$env:CUDACXX = Join-Path $cuda 'bin\nvcc.exe'
$env:CUDAFLAGS = '--use-local-env -allow-unsupported-compiler'
$env:CMAKE_BUILD_PARALLEL_LEVEL = [string]$Jobs
$env:CMAKE_GENERATOR = 'Ninja'
$env:SAPIEN_LOCAL_VERSION = $lock.local_version.Split('+')[1]
$nvccVersion = (& $env:CUDACXX --version) -join "`n"
if ($LASTEXITCODE -ne 0 -or $nvccVersion -notmatch ('V' + [regex]::Escape($lock.tested_toolchain.cuda_nvcc) + '(\s|$)')) { throw 'Private nvcc version does not match the lock.' }
$buildIdentity = [ordered]@{
    started_utc = [DateTime]::UtcNow.ToString('o')
    python = $pythonInfo
    cmake = $cmakeVersion
    ninja = $ninjaVersion
    msvc_toolset = $env:VCToolsVersion.TrimEnd('\')
    msvc_file_version = $compilerFileVersion
    nvcc_raw = $nvccVersion
    cuda_flags = $env:CUDAFLAGS
    max_compile_jobs = $Jobs
    temporary_directory = $temporaryDirectory
    physx_stage = $physxStage
    native_lock_capability = 'native_gpu_lock_sync_patch_version; runtime acceptance separate'
    lock_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $PSScriptRoot 'lock.json')).Hash.ToLower()
    prepared_inputs_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $work 'prepared_inputs.json')).Hash.ToLower()
    recipe_sha256 = [ordered]@{}
}
foreach ($recipeName in @('prepare.py', 'build_windows.ps1', 'unpack_wheel.py', 'run_check.py', 'write_msvc_prefix.py')) { $buildIdentity.recipe_sha256[$recipeName] = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $PSScriptRoot $recipeName)).Hash.ToLower() }
$buildIdentity | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $work 'build_identity.json')

# Decode captured /showIncludes bytes to UTF-8 CMake input; verify Ninja dependencies.
$prefixFile = Join-Path $work 'msvc_prefix.cmake'
Invoke-Checked $Python @('-B', (Join-Path $PSScriptRoot 'write_msvc_prefix.py'), '--compiler', (Join-Path $hostBin 'cl.exe'), '--work-dir', $work, '--output', $prefixFile)
$common = @('-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_TESTING=OFF', '-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded', '-DFETCHCONTENT_UPDATES_DISCONNECTED=ON', '-DCMAKE_POLICY_DEFAULT_CMP0169=OLD', '-DCMAKE_POLICY_VERSION_MINIMUM=3.5', "-DCMAKE_PROJECT_INCLUDE=$(Forward $prefixFile)", "-DFETCHCONTENT_BASE_DIR=$(Forward $deps)")
foreach ($entry in $lock.git_dependencies) { $common += "-DFETCHCONTENT_SOURCE_DIR_$($entry.name.ToUpper())=$(Forward (Join-Path $deps ($entry.name + '-src')))" }
foreach ($entry in $lock.archives) { $common += "-DFETCHCONTENT_SOURCE_DIR_$($entry.name.ToUpper())=$(Forward (Join-Path $deps ($entry.name + '-src')))" }
$common += "-DSAPIEN_PHYSX5_DIR=$(Forward $physxStage)"
Invoke-Checked $CMake (@('-S', $source, '-B', $nativeBuild) + $common + @("-DCMAKE_INSTALL_PREFIX=$(Forward $install)", "-DCMAKE_CUDA_COMPILER=$(Forward $env:CUDACXX)", "-DCMAKE_CUDA_HOST_COMPILER=$(Forward (Join-Path $hostBin 'cl.exe'))", "-DCUDAToolkit_ROOT:PATH=$(Forward $cuda)", '-DCMAKE_CUDA_FLAGS=--use-local-env -allow-unsupported-compiler', '-DSAPIEN_CUDA=ON', '-DSAPIEN_PROFILE=OFF', '-DKTX_FEATURE_TOOLS=OFF', "-DBASH_EXECUTABLE=$(Forward $GitBash)"))
$env:CMAKE_BUILD_PARALLEL_LEVEL = '1' # Nested OIDN ExternalProject + outer Ninja stay within Jobs.
Invoke-Checked $CMake @('--build', $nativeBuild, '--target', 'install', '--parallel', [string]$Jobs)
$env:CMAKE_BUILD_PARALLEL_LEVEL = [string]$Jobs
$oidnPlugin = Join-Path $deps 'oidn-build\devices\cuda\preinstall\bin\OpenImageDenoise_device_cuda.dll'
if (-not (Test-Path -LiteralPath $oidnPlugin)) { throw 'Expected compiled OIDN CUDA plugin is missing.' }
Copy-Item -LiteralPath $oidnPlugin -Destination (Join-Path $install 'bin') -Force

$abi = & $Python -c 'import sys; print(f"{sys.version_info.major}{sys.version_info.minor}")'
if ($LASTEXITCODE -ne 0) { throw 'Python ABI query failed.' }
New-Item -ItemType Directory -Force -Path $pythonBuild | Out-Null
$nativeLink = Join-Path $pythonBuild '_sapien_install'
if (-not (Test-Path -LiteralPath $nativeLink)) { New-Item -ItemType Junction -Path $nativeLink -Target $install | Out-Null }
$pyTemp = Join-Path $pythonBuild "temp.win-amd64-cpython-$abi\Release"
$pyLib = Join-Path $pythonBuild "lib.win-amd64-cpython-$abi\sapien"
Invoke-Checked $CMake (@('-S', (Join-Path $source 'python'), '-B', $pyTemp) + $common + @("-DCMAKE_INSTALL_PREFIX=$(Forward (Join-Path $work 'python-install'))", "-DCMAKE_LIBRARY_OUTPUT_DIRECTORY=$(Forward $pyLib)", "-DPYTHON_EXECUTABLE=$(Forward $Python)", "-Dsapien_DIR=$(Forward (Join-Path $install 'lib\cmake\sapien'))"))
Push-Location $source
try { Invoke-Checked $Python @('setup.py', '--pybind-only', "--build-dir=$(Forward $pythonBuild)", 'bdist_wheel', "--dist-dir=$(Forward (Join-Path $work 'wheels'))") }
finally { Pop-Location }
$buildIdentity['completed_utc'] = [DateTime]::UtcNow.ToString('o')
$buildIdentity | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 -LiteralPath (Join-Path $work 'build_identity.json')
Write-Output "Private wheel ready in $work\wheels. GPU/RGB acceptance must be run separately."
