# Cabinet & Pouring 十套任务实景 · 128861

`OpenCabinet` 和 `PickBottle` 各保存了 `original + variant_1…10`。组内同 env0、seed 7、原生初态、相机、灯光、曝光和 960×720。裁切使用对应物体原版帧的同一坐标。

| 实际任务 | 固定方案及恢复 | 随机复现与 A5 | 实景边界 |
|---|---|---|---|
| OpenCabinet | 柜体十套、初态及逐款恢复通过 | 随机复现、双向 A5 通过 | 可看清木纹走向、平滑漆面和把手分配 |
| PickBottle | 柜体、瓶／盖和 16 颗液滴的预定材质槽、初态及逐款恢复断言通过 | 随机复现、双向 A5 通过 | 柜体、瓶身和盖的颜色可见。单靠本组画面不能确认新印刷标签及瓶内液滴 |
| UnscrewCap | 显式 original 等价通过。variant_1 在瓶身像素断言处失败；此前两环境各阶段瓶、盖和 16 液滴的材质 getter 对照通过 | 未运行 | 近机位被机械臂挡住，三个任务相机的目标共用掩膜为 0。只保留两款，转动标记及阶段工程切换待测 |
| PourBeads | 未运行 | 未运行 | 碗和独立液滴场景无本轮图 |

关门图里木面主要呈沿门长边的条带，有些木纹显得规则。开门图能看见门内侧、层板和内外色差，机械臂遮住柜口底部和把手下段。瓶的同坐标近景里，十款仍显示与原版相似的深色印刷图样，新标签肉眼不可辨。支撑证据取自原帧固定标签小窗，均值颜色差为 0.51–4.54/255；材质 getter 的像素哈希对比通过。该证据能确认新标签的画面效果仍未达标，尚不能单独确认具体渲染原因。

实测 `5eea5a740969cdceb57914cf0327be2984e89efb`。作业 128861 在 lyg0295 物理卡 3，215 GPU 分配秒（应用 213.24 秒），`FAILED 1:0`。首次关键断言后停止，无重排，责任 PGID 和可见作业 cgroup 均已清空。整根实测峰值 166,636,327 字节。账务服务不可用，分配时间采信 Slurm 终态 RunTime。未运行 Long、完整机器人任务、训练及 A6。

## 图片和结构化证据

- [关门全景](OpenCabinet_scene_board.jpg)
- [柜门、可见顶边和把手近景](OpenCabinet_cabinet_board.jpg)
- [开门全景](PickBottle_scene_board.jpg)
- [开门柜内同坐标近景](PickBottle_cabinet_board.jpg)
- [瓶／标签可见面的同坐标放大](PickBottle_bottle_enlarged_board.jpg)
- [盖子近景](PickBottle_cap_board.jpg)
- [首个失败的机位原版／variant_1](UnscrewCap_scene_board.jpg)
- [工程检查、视觉补充和原帧索引](checks.json)
