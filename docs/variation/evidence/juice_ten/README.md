# Juice 十方案限定运行证据

当前新配色及灰白果皮修复后的正式回归见 [v3新结果](v3_regression/README.md)：作业138333全范围通过。以下保留v1历史证据，不将其套用于新配色。

2026-11-24，Server 3 / lyg0295 / G6，一个命名 GPU Index 6 共享 shard。按 pair-slurm 使用宿主 Slurm、--export=NONE、--gres=gpu:6，无嵌套 srun。既有 ms3 环境。代码为 PR19 b611faf 加本轮工作树快照，以实际输入快照和哈希为准，不冒称已提交 Git head。

|检查|结果|作业|
|---|---|---|
|OpenFridge A4/A5|11 / 20，通过|137890，COMPLETED 0:0，147 秒|
|其余五入口 A4/A5|55 / 100，通过|137918，整体 FAILED 1:0，1589 秒|
|除 CloseFridge 外五入口四步|55 对通过|137918|
|PressButton / Long / AppleToBlender 临界 reset|双向共 6 例通过|137918|
|CloseFridge 原生/原生、原生/original|各重复两次，共 4 次通过|137958，COMPLETED 0:0，44 秒|
|CloseFridge 独立进程四步|11 对通过|137960，COMPLETED 0:0，详见收据|
|六组十一方案预览|66 张；集成盖另补拍 11 张|137918 / 137961|

137918 的失败为 CloseFridge/original 第四步机器人状态超过 1e-6；该入口在 original 处停止。short_trace_trace.json.gz 保留完整初轮轨迹及失败，不将此作业写成成功。独立任务进程下四次诊断和十一对补跑通过；底层原因未定位，不能确定是缓存或其它机制。后续短步每个入口单独进程使用 --stage。未放宽数值或 RGB 门槛。

137880 因部署遗漏其它家族自动注册所需共享 variation 配置，在导入阶段失败；补齐后重跑。该作业收据已无法从控制器查询，不伪造状态，不计为通过。

## 证据与完整性

六个入口目录保存 report、identity 和完整 signatures 的 gzip，以及全部 A4/A5 原帧 SHA-256。已在本地重新计算 708 个规范 JSON signature 块哈希，全部一致，见 integrity.json。summary.json 汇总 66 行 A4、120 例 A5、66 对短步与 6 例临界检查。

137960-CloseFridge.json.gz 保存独立补跑的初态、控制器、drive 和完整轨迹；137958-*.json.gz 保存四次诊断。inputs 区分全量版、带 --stage 的补跑版、初轮预览及重取景版。final-source-sha256.txt 是全量作业前 Juice 源码身份；asset-sha256.txt 为实际安装的 60 个资产文件身份。后续只修改短步入口筛选与预览取景，不把新脚本冒作旧运行脚本。

临界夹具：PressButton 和 Long 的按钮末步前计数 3、成功未锁存，Long 阶段 4；AppleToBlender 路线锁存与运动缓存受控设置。双向 reset 后未选行状态和活动控制目标保持。这不是完整机器人成功轨迹。

服务器原帧在 /data/home/pb/juice-ten-20261124/results-137890 和 results-137918；CloseFridge 补跑在 diagnosis-137960；重取景在 diagnosis-137961。个人路径不当作团队可访问图片链接，正式 PR 仍需附图。六组本地缩略图册在 outputs/juice_ten_gallery，未批量提交大型原图。

## 范围与视觉审核

Sharpa、2env、PhysX CUDA＋GPU 渲染、seed7、noise0、固定 ID。同 reset/readback 历史的原生对照，保留活动控制目标、物理签名、原版恢复、记录、任务 RNG 和各路 RGB 检查。数值阈值 1e-6；RGB 最大差 1、最多 8 通道。默认机位被遮挡的目标保留零可见像素记录，不能当作视觉通过。

六类近景为 CPU 物理＋GPU 渲染真实任务画面，杯内苹果为明确标注的受控放置。已看图核对冰箱、苹果、底座及独立/集成盖。初轮集成盖裁掉部分底座，137961 仅调整预览相机补拍，最终图显示完整底座。目标色受原纹理明暗影响，十号苹果实景偏紫莓红。保留果梗、果皮纹理、把手、门缝、按钮、旋钮与透明杯体。

随机选择未实现。完整策略成功率、其它手型/规模/seed/噪声、长期压力及性能/显存未测。结论为作者侧限定检查通过，未替代维护者审阅，提交状态以 Git 分支为准，新 PR 由作者发起。

## 失败定位后续

已复现原始失败并修复短步验证器的实例隔离，见 [定位与修复](root_cause/README.md)。137991 使用每个原生/候选各自全新进程，66 对全部通过，源码哈希和完整数值已独立复核。原始失败与不充分的 GC 干预均保留；不修改任务或阈值。
