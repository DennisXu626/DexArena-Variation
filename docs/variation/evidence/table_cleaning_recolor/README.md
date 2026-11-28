# Table Cleaning 桶身与握柄改色：用户已审核

## 目标与改动

2026-11-27，用户审核十套颜色与浅色网丝预览后授权提交推送。基于 PR41
`c55e712762f484612ca59e710d81c9421b91758f`，沿用其已整合的 main
`6e3467b537bd67de3aeadb6758dc46d54170b96f` 及 PR12；没有整合更新的 main。
本次包含代码、检查器、证据及用户指定的 AGENTS.md 模板，不新建 PR。
实际运行使用服务器已有源码副本叠加工作树文件，身份以 SHA 而非事后提交号标识，
最终源码清单见 [source_identity.json](source_identity.json)。

三个入口 PickDebris、DumpDustpan、Long 共用 CleaningAppearance。十套新增桶身与
握柄颜色，簸箕主体、桶框及糖块原配方不变。柄部黑色网格材质和独立握套一起改色；
与簸箕主体同材质的连接颈保留主体色。桶身纹理 RGB 直接设为目标 sRGB，保留原
alpha 网孔；不再乘原黑色明暗。候选桶身视觉金属度0.05、粗糙度0.65，original
恢复原颜色、纹理及视觉参数。物理材质、碰撞、质量、几何及成功计数不变。
每环境使用私有GLB中的原纹理进行原位上传；材质绑定在同一次读取中区分主体和柄。

唯一配置为 `tasks/assets/variation/table_cleaning/v1/catalog.json`，版本
`table-cleaning-ten-v3`。沿用已有模型与UV，不新增第三方素材，来源与许可见
[簸箕档案](../../../../assets/appearance/objects/table_cleaning/dustpan/README.md)及
[垃圾桶档案](../../../../assets/appearance/objects/table_cleaning/bin/README.md)。

| ID | 簸箕主体 | 柄／握套 | 桶身网丝 | 桶框 |
|---|---|---|---|---|
| variant_1 | #2D746E | #D8C7A5 | #A9B8AC | #B0A79B |
| variant_2 | #A64D3C | #D6BA98 | #91A5BA | #384F6A |
| variant_3 | #315DA8 | #D7A469 | #B5C5D8 | #E5DCC8 |
| variant_4 | #8C9E7A | #B47D8B | #CAB7BF | #733B4B |
| variant_5 | #D5A72C | #607D8B | #A6B4BE | #454951 |
| variant_6 | #A38CC6 | #68A89E | #A9C8C0 | #286A70 |
| variant_7 | #D57B65 | #7893B2 | #A5B8CB | #304869 |
| variant_8 | #8FBFD0 | #B48E76 | #C9B6A3 | #765448 |
| variant_9 | #E5DDC9 | #789B82 | #A9BCA5 | #35584C |
| variant_10 | #535A66 | #D0A078 | #C6AD95 | #B97846 |

最小应用：`gym.make("TableCleaningDumpDustpan-Sharpa-v1", table_cleaning_appearance={"scheme_id":"variant_3"})`。
渲染入口：`python -B tools/variation/render_table_cleaning_ten.py --assets <资产根目录> --catalog tasks/assets/variation/table_cleaning/v1/catalog.json --output <目录> --views bin_side`。

## 实际验证

| 验了什么／状态 | 实际受测版本与条件 | 判据与实际结果 | 原始证据入口 |
|---|---|---|---|
| 最终浅色网丝／通过 | 工作树SHA见144256清单，Server3 G6，1env，seed7，noise0，CPU物理＋GPU渲染 | original及十套，同模型／相机／灯光／初态；实际槽颜色、纹理RGB／alpha与独立契约相符，11张原图及1图册 | [回执](144256/receipt-144256.txt.gz)、[manifest](144256/manifest.json.gz)、[日志](144256/job-144256.out.gz)、[帧哈希](144256/image-sha256.txt) |
| 柄及握套预览／复用通过 | 144248工作树SHA，版本v2，SDK与条件见manifest | original及十套，pan_handle近景，env0；用户已审核。其柄部逻辑和配方与最终版本相同，仅桶身映射及目录版本后续调整 | [回执](144248/receipt-144248.txt.gz)、[manifest](144248/manifest.json.gz)、[帧哈希](144248/image-sha256.txt) |
| CPU reset及新配方／通过 | 144256同源码，AST方法与外部替身，不加载物理引擎 | 12测试项，含十套×双向选行，另一行不变；候选RGB为精确目标值、alpha不变；恢复original材质一致 | [结果](144256/reset-cpu.json)、[原始日志](144256/job-144256.out.gz) |

144256版本：SAPIEN3.0.3、ManiSkill3.0.0b22、Torch2.12.0.dev20260408+cu128。
相机、对象姿态、qpos及逐方案实际材质槽见manifest；原图均标有ID的图册提供浏览。
网孔内暗区保留；pan_handle近景只供握柄审核，不宣称所有糖块与整只簸箕均完整可见。
最终12个PNG（11原帧＋1图册）已在本地逐一重算SHA。静态、素材档案及diff空白检查通过。

本轮作业均使用Server3／lyg0295／G6的1个共享shard：

| 作业 | 终态／退出码 | 时长 | 说明 |
|---|---|---|---|
| 144240 | FAILED 1:0 | 15秒 | 原图通过，variant_1材质断言首先发现主体被当作柄；后续未到达 |
| 144242 | CANCELLED 0:15 | 230秒 | 材质识别修正后运行；桶身仍暗，改视觉参数而停止，非完整通过 |
| 144246 | CANCELLED 0:15 | 215秒 | 收窄近景并改用原位纹理上传后取代；非完整通过 |
| 144248 | COMPLETED 0:0 | 111秒 | 两组22张；桶身版本后来由用户要求提亮，握柄证据保留 |
| 144256 | COMPLETED 0:0 | 58秒 | 最终直接浅色网丝，单组11张 |

共5次已分配提交、629共享shard秒；不是独占GPU秒，也不表示GPU实际计算利用时长。
另一次CRLF脚本提交被拒绝，未分配资源。前两项终态／时长来自执行中读取，后续
scontrol回执已清理；原始失败／中止日志保留。sacct因数据库连接拒绝不可用，
未补造独占GPU用量。现有回执见本目录，具体最后输出／未到达部分可从日志复查。

Server3完整原图位置：

- `/data/home/pb/table-cleaning-recolor-20261127/preview-144256/images`
- `/data/home/pb/table-cleaning-recolor-20261127/preview-144248/images`

由pb账号采集下载并交用户审核，尚未配置或核验xkl实读权限。图片与原始资产不随
代码重复入库；Git保留精简索引、压缩manifest和回执。

## 剩余问题与返修交接

最终生产代码与相关检查器与144256实际受测源码逐字节对应；提交的LF规范化SHA另列
于source_identity.json，便于Windows换行差异核对。所有保存结果不扩大为完整仿真回归。
新改色的CUDA双环境A4/A5、其他手型／规模和长期策略轨迹未测，旧版本通过证据不能
直接替代这些范围。CPU替身的双向隔离不是新版本实际GPU隔离通过。

用户反馈“桶身仍黑” → 取消原黑色RGB亮度映射，仅保留alpha → 144256的十套网丝
直接呈现浅色 → 用户审核后授权提交推送。后续如请求独立验收，由Dennis组织；
新增GPU范围和预算应单列。本次同时将用户提供且已存在的完整模板纳入AGENTS.md，
不重复追加，不改变其“此标准不自动授权提交新GPU作业”的要求。
