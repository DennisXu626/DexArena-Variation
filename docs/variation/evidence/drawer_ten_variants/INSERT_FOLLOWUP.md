# InsertPlug 三项补测

本轮复用 [作业 128860](runtime_001/README.md)。OpenDrawer、PickCharger 已通过的固定方案、恢复、随机复现和双向隔离继续有效。InsertPlug 的固定方案、逐款恢复、同 seed 初态、env1 reset 仍使用原证据。[GPU 补测结果与实景](runtime_002/README.md)已记录，判据如下。

| 补测 | 通过依据 |
|---|---|
| env0 Charger 恢复 | 先按 128860 的顺序做原生局部 reset。保留所得 pose、状态、灯光和固定机位，在原生入口取得壳体及双脚的材质参数，把参数临时施加于同一 reset 后物体取得独立参考 RGB。真实 reset 帧的壳体和两脚内点都须与参考逐像素相同。用同位姿 variant_4 壳体验证判据能识别错误外观。 |
| 随机复现 | seed 109 的家族选择，任务 seed 7，重建两次，整批、env1、env0、env1 的 reset 顺序与 128860 一致。逐环境逐回合比较实际编号及对象映射。 |
| 插座双孔 | 保持原 base／腕部传感器，另用从正 x 侧俯视的展示相机。original 先通过双孔门槛，此后固定相机、seed、初态、光照及曝光拍 original 和十款。 |

Charger 的实体分割与 RGB 取自同一次捕捉。按原生盒体投影区分壳体和双脚，仅统计实体遮罩内的各部件内点，每个部件至少 24 像素。隐藏部件和空遮罩会失败。较早的 env1 reset 用于重建序列，正式测试仅 reset env0。未选 env1 的状态、材质、回合记录、外观随机流与各路 RGB 必须保持，一并检查渲染对照结束后仍不变。

插座的两个暗色内衬分别至少 80 个无遮挡的投影内点，壳面与孔内亮度中位数差至少 8 个 RGB 码值。第一个 original 视角若被挡，最多尝试一次预列的第二机位。只有 original 通过才采完整相同机位的十一格。实景仍须人工审图。

## 运行与证据

```text
python -B tools/variation/check_drawer_ten_variants.py --static
python -B tools/variation/check_drawer_ten_variants.py --insert-followup --approval APPROVED.json --output NEW_RUN_DIR
python -B tools/variation/check_drawer_ten_variants.py --gallery NEW_RUN_DIR
```

第二条需新的独立 GPU 批准和 Slurm 作业，批准记录范围为 drawer_plug_insert_followup，并绑定提交和输出根。检查器保存实测提交、场景原帧及哈希、分割／部件掩膜、对照、逐环境记录和首个失败。报告仅按实际执行标记结果。
