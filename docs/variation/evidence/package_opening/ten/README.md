# Package 十套预览：Server 3 G7

- 作业123820，lyg0295，GPU Index7的一个共享shard，COMPLETED，ExitCode0:0，34秒；分配量34 shard-wall-seconds，不等于GPU活跃计算时间或整卡费用。receipt.txt为原始收据，时间按服务器原值保留。提交使用/opt/slurm/bin/sbatch、--gres=gpu:7、--export=NONE、10分钟时限、2CPU，无嵌套srun。已确认squeue --me无本人在途作业。
- 基线及全部任务／工具／utils源码SHA-256见package-ten-source.json，状态为未提交工作区快照。服务器部署与本地文件逐项匹配；不要只用Git HEAD代表本次外观版本。实际执行包装见package-ten-run.sh。
- 参数catalog版本package-opening-preview-v3，其字节身份、SAPIEN／ManiSkill／Torch版本、各视图相机、初态及逐ID回合记录见manifest.json。
- 五视图box_closed、box_open、apple、apple_in_box、plate，各original＋十套：55原始PNG＋5对照JPG。CPU物理＋GPU渲染，正式package_appearance绑定，seed7、noise0，同初态、相机和照明。每组初态和相机记录完全一致；每帧非空，同组十一张像素哈希互异。此检查不是逐材质槽或任务成功验证。
- image_hashes.json记录60图的文件SHA-256；asset_hashes.json记录实际使用资产路径中107个模型／材质／贴图文件的本次哈希，未复制原始资产进仓库。服务器原始图与日志保留/data/home/pb/package-ten-20261120，未覆盖旧作业。Codex本轮visualizations/package-ten保存对照图，PR需要附图，不能只留个人本机链接。
- 助手已目视检查主要对照板，确认第八套深海蓝与第三套绿有区别，苹果白／深黑紫呈现目标明暗；最终用户审美反馈待补。
- 新增八套只做外观预览；没有双环境CUDA隔离、original恢复、几何／碰撞／质量完整签名、长任务完整机器人成功轨迹、性能或显存结果。旧两套87021证据不扩展至新八套。
- CPU检查：原original／两套既有定义不变；旧苹果配方在合成随机RGB图上的输出与HEAD函数逐像素相等；十个改色输出不同。仓库check_static.py与git diff --check通过。未commit／push。
