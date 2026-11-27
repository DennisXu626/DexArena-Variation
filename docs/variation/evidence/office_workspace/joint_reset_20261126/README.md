# Windows CUDA 双环境位置与外观联合 reset 回执

本批于 11 月 26 日在 Windows RTX 4070 Laptop 上以 PhysX CUDA、两个环境、`obs_mode="state"` 运行。三个最终进程均以 0 退出。回执保存了双向隔离断言的汇总、env1 远点 XY 的最大分量误差和拒绝数。六次 reset 的逐槽绝对位姿、完整状态快照、逐例异常文本和相机原帧均未落盘。11 月 27 日整理已有文件时没有重跑仿真。

| 任务 | 启动命令、受测提交、退出码 | 原始结果与 SDK／检查器哈希 | env1 远点最大 XY 误差 | 拒绝计数 |
|---|---|---|---:|---:|
| OpenLaptop | [process.json](OpenLaptop/process.json) | [result.json](OpenLaptop/output/result.json) · [private_sdk.json](OpenLaptop/output/private_sdk.json) | 1.86264515e−8 m | 7 |
| TypeKeys | [process.json](TypeKeys-final/process.json) | [result.json](TypeKeys-final/output/result.json) · [private_sdk.json](TypeKeys-final/output/private_sdk.json) | 1.86264515e−8 m | 7 |
| ClickMouse | [process.json](ClickMouse-with-deps/process.json) | [result.json](ClickMouse-with-deps/output/result.json) · [private_sdk.json](ClickMouse-with-deps/output/private_sdk.json) | 8.94069672e−8 m | 5 |

**受测身份。** 三个进程均记录本地集成提交 `ef1408a1dd459248cead48a4acd1c9287e2ed4de`。对应 GitHub 合并预览 `80780d3`，父提交为 `main@8629653` 和 `#43@e349511`，完整 tree 为 `f3f1ca754297b6497c248cabe54372d431073e64`。各 SDK 回执的 `launcher.checker_sha256` 与所附检查器原字节相同。另附集成树 Git blob 索引，标明归档时的校验，与当时记录的哈希分列。静态资产审验单独存档，联合 reset 进程没有逐个打印加载资产的哈希。[合并身份回执](remote.json) · [源码索引](source-identity.json) · [集成资产审验](merged-assets.json) · [原检查器](check_reset.py)

**构造参数。** 检查器的 `check()` 直接构造传给 `gym.make` 的参数，进程命令中的 `--task` 决定注册 ID 和外观通道。三项均用 `position_workspace=True`、`pd_joint_pos`、`reconfiguration_freq=0`，完整 reset 的 seed 为 717。笔记本与键盘同时开启机身和键帽，TypeKeys 另指定 `model_id="13106"`；鼠标开启 `mouse_appearance`。完整字段、PhysX 容量、按任务展开的请求和断言值见离线索引。该索引按已校验的检查器还原，原进程没有单独打印 kwargs。[request-index.json](request-index.json)

**执行顺序与可复核的读回。** 下表的坐标是请求目标，单位 m，为各自环境的桌面世界 XY，绕 +Z 的偏航相对设备标称为 0°。脚本先只 reset env1 到 `far`，再只 reset env0 到旧显式布局的标称点。表中方案来自检查器读回后执行的断言；原始 JSON 仅存 `schemes`、远点误差和 `peer_state_equal_both_directions`。env0 标称点通过 `torch.allclose(atol=1e-5, rtol=0)`，没有落盘具体误差。每次 reset 前后均以 `torch.equal` 比较未选槽完整状态，并检查其布局记录。[执行与断言](check_reset.py) · [逐方向请求](request-index.json)

| 任务 | 先只 reset env1，env0 保持 original | 再只 reset env0，env1 保持前次方案 |
|---|---|---|
| OpenLaptop | far (0.037, −0.020)，机身／键帽 variant_1／variant_2 | 标称 (−0.063, 0)，机身／键帽 variant_1／variant_2 |
| TypeKeys | far (−0.149, −0.020)，机身／键帽 variant_1／variant_2 | 标称 (−0.289, 0)，机身／键帽 variant_1／variant_2 |
| ClickMouse | far (0.080, −0.33999999)，ivory_matte | 标称 (−0.100, −0.320)，ivory_matte |

**19 个非法组合。** 原检查器对每个请求捕获 `ValueError`，并比较拒绝前后的整批物理状态、布局记录／计数、外观方案／计数。全部断言完成后才写入按用例数计算的 `rejected_cases`。三个原始结果分别为 7、7、5。没有独立的 19 行异常日志；`illegal_options_from_checker` 列出源码展开的精确输入。原状态与原帧若需按 #51 逐行复核，由独立执行层另批留档。[拒绝逻辑](check_reset.py) · [输入清单](request-index.json)

**团队原件。** Server 3 以账号 `lyt` 读取 `/data/home/lyt/dexarena-issue18-20261120-env/runs/pr43-windows-joint-reset-06f47538c02e/`。目录保留原层级，`originals.zip` 同时包含 27 份原件，SHA-256 为 `06f47538c02e1f6f2a56890ee775a3a69e4e2ebd4869ba5e1084403b6ea693d6`。归档后以该账号打开 ZIP 和全部解出的文件并逐字节比对。GitHub 中 `verbatim` 文件与原件同字节，其余副本仅替换本机目录前缀。首轮 TypeKeys 和缺少 CoACD 的鼠标首跑单列，未重复计入三个成功结果。[逐文件 SHA-256 对照](SHA256.tsv) · [TypeKeys 首轮](TypeKeys/process.json) · [ClickMouse 首跑](ClickMouse/stderr.log)
