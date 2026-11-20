# Juice 限定运行证据

本目录为 2026-11-20 已有运行的精简归档，不要求审阅者登录 Monica。结果待 Dennis 最终审阅，不表示批准合并。

| 文件 | 用途 |
|---|---|
| [results.json](results.json) | 六任务断言、逐槽签名引用、成本、方案记录、原始结果和图片 SHA-256 |
| [signatures.json](signatures.json) | 去重后的完整材质／纹理身份与物理参数；引用值为规范 JSON 内容 SHA-256，可独立展开比较 |
| [manifest.json](manifest.json) | 实际部署源码、catalog、60 个私有资产文件、临时派生文件和脚本 SHA-256；包版本 |
| [receipts.json](receipts.json) | 本人相关作业的 scontrol 导出；旧作业已过期者明确保留原错误 |
| [verify.py](verify.py)、[verify_remaining.py](verify_remaining.py) | 两次最终作业实际执行的检查脚本，未做代码改写 |
| [run.sh](run.sh) | 作业包装脚本归档，原服务器工作根替换为显式 RUN_ROOT 变量；其余逻辑保留 |

生产源码位于 PR 的 tasks/juice_preparation；manifest.source 是部署文件的字节哈希，核对时注意 Git 换行转换。manifest 为运行后抓取，最终作业提交后部署源码未改变；不是伪造运行前 Git 提交号。最终运行的是从固定 base 加本分支未提交改动组成的私有部署。

最终作业 123675 执行 run.sh verify Long；123676 执行 run.sh verify_remaining。实际提交参数为 sbatch --parsable --gres=gpu:7 --export=NONE --time=00:06:00 -c 2 --job-name=pb-juice-final，输出 parallel-%j.out；没有嵌套 srun。前者 COMPLETED 0:0，48 秒；后者 COMPLETED 0:0，122 秒。每个分配 idx7 的一个 shard，合计 170 shard-wall-seconds，无法据此推算实际 GPU 活跃计算秒或独占整卡费用。

收据时间按服务器原值保留，不擅自推断时区。WorkDir 等公共前缀替换为 $RUN_ROOT，未包含凭据或无关用户作业；没有在途 GPU 作业由本轮验证继续持有。私有部署、资产副本、TMPDIR、PNG 与 JSON 保留待审，未清理或触碰共享资产。早期失败／排障作业不作为通过依据；部分 scontrol 已报 Invalid job id，当前无法从控制器追溯，不能宣称它们不存在或零成本。

物理基线为同一适配源码关闭外观的运行，而非未经改动的旧版本；源码为支持两个环境修改了本家族的单环境假设。限定范围是 Sharpa、2env、seed7、noise0、固定方案、初态附近局部 reset 和 16 步零动作。不是完整机器人任务、其它手型／规模、随机 GPU 或成功临界状态隔离验收。

结果精简仅将重复字典变为内容寻址引用，数值与纹理身份未舍弃；原始大 JSON 和 PNG 留在 verification-123675、verification-123676 输出目录，raw_result_sha256 和 image_sha256 可复核。图片需由提交者附 PR，不能只提供个人本地文件路径。

静态核对见[static_checks.json](static_checks.json)。check_static 和 Juice 源码／结果／签名核对通过。原归档检查的字节哈希受本机既有 Cabinet JSON 的 CRLF 影响，直接运行失败；仅在内存对 JSON 作 LF 规范化后全项通过，未改共享检查脚本或 Cabinet 素材，不能将此写成原命令直接通过。
