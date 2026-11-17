# Table Cleaning 双环境外观验证

实现支持拣碎屑、倒簸箕和长任务三个 Sharpa 入口。所用基线为 `acd6ba232b8da7a97fd313aa3df8a9f595fd55e0`。方案及配方见[唯一运行目录](../../tasks/assets/variation/table_cleaning/v1/catalog.json)。

```python
env = gym.make(
    "TableCleaningLong-Sharpa-v1",
    num_envs=2,
    sim_backend="physx_cuda",
    table_cleaning_appearance={"per_env": {
        "0": {"scheme_id": "variant_1"},
        "1": {"scheme_id": "variant_2"},
    }},
)
env.reset(options={
    "env_idx": torch.tensor([1], device=env.unwrapped.device),
    "table_cleaning_appearance": {"scheme_id": "original"},
})
```

省略 `table_cleaning_appearance` 时使用任务原材质。启用后支持 `original`、`variant_1`、`variant_2` 的显式选择。选中环境的有效方案在 `env.unwrapped.cleaning_appearance.records` 记录。垃圾桶仍为静态刚体，并行时在建场按环境选定位置，局部 reset 沿用该位置。簸箕和桶的视觉 GLB 使用逐环境副本，碰撞使用原 GLB 和原缓存。碎屑纹理逐环境独立绑定，选择方案时原地上传颜色像素。保留桶身纹理及透明材质、簸箕握套和现有碰撞配置。

## 实际检查

Server 3 G0 作业 `90672` 正常退出，Slurm 分配 31 秒。四组单环境预览来自作业 `90644`。使用 PhysX CUDA 双环境和 GPU 渲染。两环境使用不同方案，各自的簸箕主体、桶框和 3 个糖块共 5 个槽与关闭外观的对照不同，两环境的场景图也分别出现变化。期间只重置 env1。env0 的材质、方案记录及人类相机 RGB 完全一致。机器人关节、物体位姿与速度、任务状态的数值最大差为 1.19e-7。env1 切回原版后，各材质槽和 RGB 与独立对照一致。收集 reset 对照后另执行一个 GPU 物理步，三个任务均正常运行。

[结构化结果](evidence/table_cleaning/summary.json)保存逐场景差值和实际回合记录。本次核对固定方案与局部 reset。完整机器人操作、其它规模、随机方案及资源成本未测。验证脚本使用预览脚本里的缓存校验函数，核对缓存记录的源 GLB MD5 和原分解参数后复用，以适配未安装 CoACD 生成器的渲染环境。以下命令用于已有授权的作业，从仓库根目录运行。

```bash
PYTHONPATH="$PWD" python -B tools/variation/check_table_cleaning_parallel.py \
  "$TABLE_CLEANING_ASSET_ROOT" "$OUTPUT_PATH"
```
