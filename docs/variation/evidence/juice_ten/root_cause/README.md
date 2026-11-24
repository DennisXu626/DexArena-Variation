# 短步失败定位与修复

原始失败 137918：CloseFridge/original 初态及前三步逐值一致，第四步 env1 左手机器人出现差异，61 个输出标量不同，最大差 1.2307605743408203。原生/候选初态与控制目标一致，并不保证两次物理后端的隐含状态一致。

代码事实：旧检查器执行 `native=make(task,None);env=None`，在创建下一原生实例之后才释放上一候选。ManiSkill 3.0.0b22 的 BaseEnv.close 调用 _clear，将 self.scene/agent 等清空并 gc.collect；任务自己的 fridge/apple 等字段仍持有 actor，而 actor 持有场景。已关闭环境的 Python 引用仍在时，场景不一定销毁。

137990 对照保持原先前序 OpenFridge、AppleToBlender 全十一方案的历史：旧流程在下一次创建之前场景弱引用存活数为 1，并复现与 137918 相同的 CloseFridge 第四步差异。显式清空引用并 GC 后，创建之前存活数为 0、CloseFridge/original 通过，但 OpenFridge/variant_1 改为失败。因此排除“仅增加 GC 就完全修复”的结论。

可确认的是：检查器没有真正隔离各实例，进程内构造/销毁历史影响这组 CUDA 物理的逐值回归。不能据此声称已定位 PhysX 内部的具体缓存、接触求解器或驱动缺陷。场景残留是实测到的检查器缺陷；原生可观察初态不包含后端全部隐含状态。

最终修改：每个原生和候选实例各用独立 Python worker；父进程不导入物理模块，串行 subprocess.run 等待退出后再启动下一个。每个 worker 内仍 num_envs=2，固定 reset seed7、noise0；先比较初态/控制器/drive，再比较同样四步动作。保留旧动作以避免通过改变刺激掩盖问题。旧 .01*sin 是绝对关节目标，不是围绕初态的小扰动，修正文案，不修改任务生产代码或成功条件。

137991 在 G6 完成全量 66 对复验，COMPLETED 0:0，未放宽 1e-6。独立本地复核初态、控制器、drive 与完整四步轨迹最大差为 0.0。见 verification.json、process-isolated-trace.json.gz 和收据。历史失败、无效 GC 修复尝试与最终验证分别归档。父进程每次等待 worker 完全退出，不再依赖 Python GC 作为后端隔离边界。

结论：已修复验证器的实例隔离缺陷，并在原先同样的动作与容差下全量通过。此次定位止于进程内场景生命周期/后端历史层面；尚未定位 PhysX 内部究竟哪项隐含状态造成第四步分歧，不声称修复了引擎或驱动。
