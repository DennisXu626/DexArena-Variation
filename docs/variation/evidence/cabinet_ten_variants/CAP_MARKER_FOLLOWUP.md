# UnscrewCap 标记掩膜诊断

[作业 128943 真实分割复验、十款实景及首个阶段阻断](runtime_004/README.md)。下文保留 CPU 诊断原始结论。

作业 `128933` 的两张原版 PNG 都显示盖顶红条。问题发生在检查器的深度投影。SAPIEN 3.0.3 的 `RenderShapeBox.vertices` 读取共享单位盒，盒子的实际半尺寸单独存为渲染缩放，并通过 `half_size` 暴露。旧检查器对盒子尝试读取 `scale`，回退到 `1`，把厘米级标记当成单位盒，深度测试后盖体上的标记像素为零。修改只补上盒子的 `half_size`，三角网格仍用原有 `scale`。保留深度遮挡、实体分割交集和一像素内缩，以及至少 24 个标记像素、80 个盖体像素的门槛。 [SAPIEN 3.0.3 形状和变换实现](https://github.com/haosulab/SAPIEN/blob/731622eac5b140b320076c8a1b6eb4b553c3ccd4/src/sapien_renderer/render_shape.cpp#L45-L104) · [Python 属性绑定](https://github.com/haosulab/SAPIEN/blob/3.0.3/python/pybind/sapien_renderer.cpp#L749-L766)

| 128933 原版原帧 | 运行时原检查器盖体／标记像素 | CPU 旧几何内缩像素 | CPU 修正几何内缩像素 | 与原 RGB 红条重合 |
| --- | ---: | ---: | ---: | ---: |
| `UnscrewCap_native_view0.png` | 4,810／0 | 0 | 204 | 204 |
| `UnscrewCap_native_view1.png` | 7,221／0 | 0 | 286 | 286 |

CPU 重放核对两张 PNG 以及盖体、瓶身、元数据的原始哈希，按冻结源码的相机、网格、标记尺寸和初态重建几何。旧作业只保存了 RGB 和分割计数，CPU 用盖网格轮廓近似实体分割，仅用于离线复现。青色描边是投影位置，红色像素只作为独立离线对照。下一次作业仍使用同帧真实实体分割、深度及原阈值。 [原帧投影对照](cap_marker_replay.jpg) · [重放数据](cap_marker_replay.json) · [原运行结果](runtime_003/README.md)

新增检查器入口 `--followup remaining`，复用 `128933` 已通过的 PickBottle 瓶签、恢复及隔离，只跑 UnscrewCap、正式 PourBeads 和独立瓶外液滴。首个关键失败仍立即停止并保留结果。生产文件保留 `87afa53` 的实测版本。CPU 重放及静态检查已完成，真实分割和后续任务仍待新授权后验证。PR 保持草稿。
