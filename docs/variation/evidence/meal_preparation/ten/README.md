# Meal 十套外观：G3 渲染与限定验证

配色经用户批准后在 Server 3 / lyg0295 / G3 执行。当前为作者侧限定验证，不代表 PR 已审阅／合并。

## 作业与身份

- 123800：FAILED，ExitCode 1:0，16 秒。新验证脚本误用空配置，未启用外观，盘子各方案完全同图的断言正确阻止通过。修正为显式 enabled=true；未改生产任务代码。
- 123801：COMPLETED，ExitCode 0:0，127 秒。预览和四入口验证全部完成。
- 两次均申请命名 GPU Index 3 的一个共享 shard，合计 143 shard-wall-seconds；不等于 GPU 活跃计算秒或独占整卡费用。更早一次 sbatch 因 DOS 换行拒绝，未创建作业。
- 提交方式：`/opt/slurm/bin/sbatch --parsable --gres=gpu:3 --export=NONE --time=00:15:00 -c 2 --job-name=pb-meal-ten -o /data/home/pb/meal-ten-20261120/slurm-%j.out run.sh`；无嵌套 srun。作业结束后 squeue --me 为空。
- 基线 HEAD aee41a3 加本分支未提交改动；不是虚构的已提交运行版本。[部署哈希](deployed-sha256.txt)已逐项与本地文件核对。[全源码清单](../ten_source_manifest.json)记录部署快照来源；[执行脚本](run.sh)及两份 receipt 原样保留。
- 实际包版本及 catalog SHA-256 见 preview_identity.json 和四个入口 identity.json。独立目录 /data/home/pb/meal-ten-20261120；未覆盖旧作业和共享素材。

## 预览

preview_manifest.json 保存同初态、seed7、同相机位姿／视场角。五类对象各 original＋十套，共55张原始PNG和5张对照JPG；CPU物理＋GPU渲染，使用真实任务原生reset状态，不是机器人成功轨迹。box 为合盖近景，内底在番茄近景可见；盘底和完整开盖内侧没有单独审美图。五组均有十一张不同像素的图；五张对照板已经助手目视核对，用户对实际渲染的最终意见待补。

原始图保留服务器 results-123801，摘要 [图片哈希](image-sha256.txt)。本地对照图在 Codex 本轮 visualizations 的 meal-ten 目录；提交 PR 时附图，不能只保留本机链接。

## 四入口结果

| 入口 | 方案 × reset方向 | 每次恢复槽数 | 未选行最大状态差 | Human RGB 最大差 / 最大变化通道数 |
|---|---:|---:|---:|---:|
| 开盒 | 10 × 2 | 12 | 1.19e-7 | 1 / 1 |
| 放面包 | 10 × 2 | 22 | 2.38e-7 | 1 / 1 |
| 舀番茄 | 10 × 2 | 22 | 2.38e-7 | 1 / 5 |
| 长任务 | 10 × 2 | 22 | 2.38e-7 | 0 / 0 |

- 每套检查两环境所有实际绑定角色的颜色、粗糙度、金属度；贴图比较实际download像素与按配方生成／缩放像素，RGBA完全相等。详见各 *_results.json 中 semantic 字段。
- 两方向局部reset分别让 env1、env0 恢复original。恢复槽逐项比较独立关闭外观环境的材质参数、纹理像素身份及其它已列通道，运行内全部断言通过；完整native/restored逐槽字典未另存，只归档通过槽数。
- 未选行渲染材质、回合记录、独立外观随机流及任务逐环境随机流保持；get_state_dict 状态阈值1e-6，Human RGB阈值最多8个通道变化1级。
- 每入口在检查结束后执行4步零动作，未失败；当时一行是original，另一行是variant_10。这不是十套各自的动态测试。

## 范围限制

限定 Sharpa、2env、seed7、noise0、默认程序盒、显式方案及初态附近局部reset。未验完整机器人成功轨迹、成功临界阶段、其它手型／规模／随机模式／长期压力。没有重新测性能、显存增量或完整物理几何／碰撞签名；生产变更只有外观catalog和贴图改色，未改任务／几何／物理代码。

RGB隔离只查Human相机，未遍历机器人相机；原版恢复有逐槽材质比较，没有新增独立原版RGB逐值对照。配方像素期望复用生产bake_texture，证明绑定结果一致，不能替代独立审美验收。
