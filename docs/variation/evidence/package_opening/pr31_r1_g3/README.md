# PR31-R1 控制目标覆盖修复及 Server 3 G3 复验

审阅冻结 head 为 `1773a3c84ced61795c937e945aa96bb749e5846c`；本次实际受检修复提交为 `425a54a510b1a4b843279e30d41f8f6c69f428be`，从该分支直接导出源码运行。没有合并审阅 base `58b5462`，因此本次结果是修复分支的作者复验，不冒充原审阅集成 tree 的复验。完整源码 SHA-256 见 [source_hashes.json](source_hashes.json)。

## 修复

旧 A5 依赖 `get_state_dict()`，指定运行时的空 controller serializer 会漏掉实际控制目标。检查器现直接采样所有手臂阻抗控制器的 `_target_qpos`、机器人 articulation drive targets 和 drive velocities，按环境保存独立快照、签名和数值比较。缺失、空批次或非有限目标立即失败。A5 对未选环境比较 before/after，对选中环境比较同 reset 历史的 native。原有数值 `1e-6` 和 RGB 容差、三入口及双向 reset 序列不变；生产任务、配方和控制器实现未改。

CPU 回归调用正式采样和比较函数：在序列化模拟状态保持不变时，分别篡改左右臂目标、drive targets、drive velocities；两种 reset 方向均必须报错。4 项测试在本地及 Server 3 指定解释器通过，见 [cpu-tests.log](cpu-tests.log)。CPU 测试使用替身，不宣称创建了真实仿真环境。

## 实测结果

|入口|A4 original＋十套|双向 A5|随机重建复现|未选控制目标最大差|选中目标相对 native 最大差|
|---|---:|---:|---|---:|---:|
|OpenPackage|11/11|20/20|通过|0|0|
|ExtractApple|11/11|20/20|通过|0|0|
|Long|11/11|20/20|通过|0|0|

独立归档脚本重新读取全部 60 例目标快照并逐值比较；三个入口的 116、118、118 个签名块均重算 SHA-256 匹配。各入口 [report](open/report.json.gz)、[signatures](open/signatures.json.gz) 以 gzip 保存；extract/long 目录具有相同结构。运行身份和依赖版本见各入口 identity.json，汇总见 [summary.json](summary.json)。

## 48 格渲染复核

按原审阅矩阵的三入口 × variant_3～10 × env0/1，重新输出全部 48 格的正式任务相机原帧，共 176 张 PNG。summary.json 的 review_cells 保留审阅参考色、实际 records、每格相机原图路径和 SHA-256。联系表只用于浏览，原 PNG 保持原始字节。逐格实际 scheme ID、逐材质槽语义、原版恢复和 A5 图像容差均由正式检查器通过。

目视复核了本次原相机联系表与补充对象近景：各套盒身／翻盖有对应差异，variant_8 为深海蓝／冰蓝，原粉色底带保留；苹果的白色、深紫色、青色等目标明暗和纹理可辨，盘子配色对应。原生视角有机器人遮挡，不能仅凭每格原生图独立辨认全部对象。为此在同一 G3 追加五视图近景作业，55 张原 PNG 与5张对照 JPG 保存在 [supplemental_preview](supplemental_preview/manifest.json)。该近景为 CPU 物理＋GPU 渲染、单环境、修改观察相机的对象配色补充；不替代三入口双环境 A5，也不声称对被遮挡部分完成独立逐像素颜色测量。

## 作业与复现

- 主作业 `135140`：Server 3 / lyg0295 / G3，`COMPLETED`、`0:0`，455 秒。
- 补充近景 `135189`：同节点 G3，依赖主作业成功后串行运行，`COMPLETED`、`0:0`，34 秒。
- 共 489 shard-wall-seconds；每项申请一个 G3 共享 shard，不等于整卡或 GPU 活跃计算秒。2 次提交，0 次重提；收尾 squeue --me 为空。
- 两项均使用 `/opt/slurm/bin/sbatch --export=NONE --gres=gpu:3 -c 2`，无嵌套 srun。实际包装为 [run.sh](run.sh) 和 [run-preview.sh](run-preview.sh)。解释器为 `/mnt/ceph2/wj/miniconda/envs/ms3/bin/python`，只读使用现有 Package 资产。
- [receipt.txt](receipt.txt) 来自 Slurm scontrol。sacct 当时无法连接 accounting 数据库，未取得 accounting 收据。
- [archive.py](archive.py) 是本次独立结果校验和打包脚本；[raw_image_hashes.json](raw_image_hashes.json) 记录全部原始 PNG；[file_hashes.json](file_hashes.json) 记录打包文件身份。
- 服务器完整结果保留于 `/data/home/pb/pr31-r1-fix-20261123/results-135140`，补充近景于同目录 `preview-135189`。Git 中保存48格全部原帧、补充近景、完整报告和签名；其余 A5 原帧在服务器保留，并提供哈希清单。

本轮没有重新执行历史33对四步回归；旧证据保留。限定 Sharpa、2env、seed7、noise0、初态附近局部 reset；未测完整机器人任务成功率、长期压力或其它部署配置。待审验层重新查收。
