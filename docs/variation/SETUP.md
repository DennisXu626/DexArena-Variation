# 环境与素材准备

所有命令从仓库根目录执行。这里的资源准备供获得运行授权后使用；建仓轮没有执行安装、下载对象包、仿真或训练。

## 运行平台和依赖

已验收平台是 Linux + NVIDIA GPU：Python 3.10、torch 2.6.0、SAPIEN 3.0.3、ManiSkill 3.0.0b22、numpy 2.2.6、gymnasium 0.29.1。ManiSkill负责环境及并行管理，SAPIEN提供物理和渲染。单环境默认 `physx_cpu`，多环境默认 `physx_cuda`；两者的画面仍需要GPU渲染。

这些版本来自M1／M2实际环境清单，不是本轮重装结果。保存的证据没有完整锁定CUDA wheel、驱动和全部间接依赖，不能仅据上述版本重建出逐字节相同的环境。优先向维护者申请实验室已验证环境的使用说明和资源许可，把其Python解释器路径填入自己的 `.local/paths.env`；不需要任何算法工程或训练检查点。

Windows本轮只用于编辑、JSON／Python语法和Git静态检查；Windows仿真、macOS、无NVIDIA笔记本、新安装环境均未验证。不要在共享环境执行升级。

新机器若必须安装，可先在独立环境尝试以下**候选步骤**，失败时带版本／错误向维护者核对，不将其标为已验证安装配方：

```bash
conda create -n dexarena-variation python=3.10
conda activate dexarena-variation
# torch的CUDA wheel需按本机GPU及驱动选择，下面未锁定CUDA构建。
python -m pip install torch==2.6.0
python -m pip install sapien==3.0.3 mani_skill==3.0.0b22 numpy==2.2.6 gymnasium==0.29.1 pillow
```

上游的[安装参考](../GETTING_STARTED.md)还覆盖训练／数据处理；其中 `--upgrade mani_skill` 和其它torch版本不是本试点的锁定方案。若导入还缺间接依赖，先向维护者索取环境清单，不复制整套训练栈来试错。

## 本机路径

```bash
mkdir -p .local outputs/variation
cp examples/variation/paths.example.env .local/paths.env
# 编辑 .local/paths.env，填本机解释器和ManiSkill素材目录后：
source .local/paths.env
"$DEXARENA_PYTHON" --version
```

`.local/`、`outputs/`、个人环境文件不入库。不要把令牌写进路径文件。MS_ASSET_DIR是ManiSkill管理素材的目录，**不是**本项目瓶／柜网格目录。任务对象位置由当前源码固定为下表的仓库内路径，本轮没有增加路径加载框架。

## 素材来源与目标目录

| 类别 | 来源／授权 | 本地位置 |
|---|---|---|
| 瓶、盖、柜 | [SIPAIR/DexArena数据集](https://huggingface.co/datasets/SIPAIR/DexArena)的 `assets/task_object_meshes/cabinet_pour/`；先申请数据集访问并遵守其条款 | `tasks/assets/task_object_meshes/cabinet_pour/`，Git忽略的**自有可写副本** |
| Panda、Sharpa、移动底座、相机外壳及组合URDF | 官方Git基准已跟踪资源及原有授权／署名 | `tasks/assets/franka_description/`、`sharpa_hand_meshes/`、`mobile_base_meshes/`、`marvin_wrist_camera_meshes/`、`urdf/`；随克隆取得 |
| 桌面、地面及默认场景 | 已验证ManiSkill安装包／其合法素材渠道；任务使用上游table builder | 安装包的table资源与本机MS_ASSET_DIR；项目入口 `tasks/scene_builders/table.py` |
| 三种variation小贴图 | 团队用Pillow制作的原创图案；随代码迁入，未分发字体或第三方图片 | `tasks/assets/variation/cabinet_pouring/v1/` |

原对象包不重新分发进本Git仓库，私有可见性也不替代第三方许可。[上游资产说明](../../tasks/assets/README.md)、[代码许可证](../../LICENSE)和既有NOTICE保留。若机器人资源目录没有单独许可文件，不能据此推断模型可任意再分发；仍需核对其原来源条款。

### 优先复用有授权的现成对象包

让维护者提供**有权使用的**Cabinet资产目录和对应来源清单，替换下面示例源路径：

```bash
export DEXARENA_CABINET_SOURCE=/path/to/authorized/cabinet_pour
mkdir -p tasks/assets/task_object_meshes
cp -R "$DEXARENA_CABINET_SOURCE" tasks/assets/task_object_meshes/cabinet_pour
```

目标 `cabinet_pour` 应原先不存在，避免拷成 `cabinet_pour/cabinet_pour`。不要直接把目标软链接到共享只读源：原任务会在瓶资产附近写生成的 `bottle_screw*.urdf`，机器人导入也可能在组合URDF目录生成派生文件，当前用户必须有写权限。

### 自行通过HF取得

在数据集网页完成正常访问申请，使用个人认证，不能共享token：

```bash
hf auth login
hf auth whoami
hf download --help
export DEXARENA_ASSET_REVISION=b197a198fe50f41d70f563cfa7c88d3cc9f528b6
# hf 2.x使用 --type；旧版若帮助中提供 --repo-type，则仅替换此参数。
hf download SIPAIR/DexArena --type dataset --revision "$DEXARENA_ASSET_REVISION" \
  --include 'assets/task_object_meshes/cabinet_pour/**' --local-dir .local/hf-assets
mkdir -p tasks/assets/task_object_meshes
cp -R .local/hf-assets/assets/task_object_meshes/cabinet_pour tasks/assets/task_object_meshes/cabinet_pour
```

仅取本试点对象，不下载示范、模型或其它任务包。该HF revision是M1／V1选定视觉资源的参考，M1只逐项匹配了8个选定文件；**不表示整套运行资产已证明与该HF包一致**。首次下载后按 [来源清单](PROVENANCE.md) 核对必要目录，向维护者取得完整试点资产清单再决定是否用于正式验证。401／403请检查访问批准及个人登录，不把token粘进命令或Issue。

至少要有 `bottle_4403/body_vis/original-3.obj` 和MTL、`images/texture_1.jpg`、`lid_vis/original-2.obj` 和MTL、`meta.json`、`body_col_profiled/*.obj`、`body_col_hand/*.obj`、`lid_col_solid/part_solid.obj`，以及PickBottle的 `cabinet/mobility.urdf` 及其引用网格。不能只下载瓶的视觉文件就宣称素材齐全。

## 子模块和已跟踪资源

官方只记录 `libs/Isaac-GR00T` 子模块，锁定 `ab88b50c718f6528e1df9dcbaf75865d1b604760`，来源 `https://github.com/NVIDIA/Isaac-GR00T`。子模块是独立Git仓库的固定提交引用。它用于上游GR00T算法，本Cabinet试点不依赖它，克隆不需要 `--recurse-submodules`，本轮也没有下载／初始化它。`.gitmodules` 和gitlink均保留；机器人网格是主仓库已跟踪文件，不是该子模块里的依赖。

## 常见问题

- **找不到瓶／柜或缺碰撞目录**：核对目录是否多套一层，MTL相对贴图路径是否完整，授权包是否包含profiled／hand碰撞文件；不要拿近似模型代替。
- **缺依赖或版本不匹配**：核对正在用的解释器及上述版本，携带错误向维护者核对。不要升级共享安装或要求队友安装个人算法工程。
- **局部reset后渲染报场景修改错误**：本仓库包含已验收兼容修复；确认没有只拿到首轮补丁、没有丢失父任务的渲染刷新方法。不同核心版本未验证，先报告，不猴子补丁改核心。
- **默认相机被机器人遮挡**：这是原相机初态的已知限制，不等于材质丢失；本轮没有调整相机，也不声称原视角已适合视觉训练。
