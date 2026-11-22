# Drawer & Plug 十套任务实景 · 128860

三个任务各保存 `original + variant_1…10` 的固定方案实景，env0、seed 7、960×720，组内固定初态、机位、曝光和灯光。缩略图与裁切从原帧生成，素材颜色保持。33 个固定方案格齐全，另外保留双向局部 reset 的比较帧。

| 实际任务 | 固定方案、绑定、同 seed 初态和逐款恢复 | 随机复现 | A5 双向局部 reset |
|---|---|---|---|
| OpenDrawer | 通过，抽屉 | 通过 | 两个方向通过 |
| PickCharger | 通过，抽屉和 Charger | 通过 | 两个方向通过 |
| InsertPlug | 通过，插座和 Charger | 未运行 | reset env1 通过。reset env0 在 Charger 像素判据停止 |

InsertPlug 第二方向，未选 env1 的状态、材质、外观记录、随机流和各路 RGB 检查先通过，所选 env0 的恢复材质检查也通过。插座 base 相机掩膜共有 9,024 个像素发生变化。Charger 前后位置有明显位移，三个相机的共用目标掩膜都是 0 像素，既定像素断言无法判断。首次断言失败后退出，未重提。原图可以辨认壳体，但这项 A5 仍未通过。

闭屉的机械手遮挡最低一层把手的一部分，台面、可见侧板和抽面的木纹可辨。开屉图能分辨内箱底板、内壁、外壳和抽面。插座例图的机械手遮挡壳体顶部及一个孔，不能用这组固定帧确认双孔清晰度。Charger 主体颜色与双插脚能区分，原金属和各类塑料的光泽细节留给人工审图。

实测提交 `f244804b92bb0ae43984ebce2876051c33d3f50b`。作业 128860 在 `lyg0295` 物理卡 3 运行 71 分配秒（应用 68.43 秒），一次提交，`FAILED 1:0`，无重排，责任 PGID 及可见作业 cgroup 均已清空。整根实测峰值 204,648,944 字节。账务服务不可用，分配时间采信 Slurm 的终态 RunTime。未运行 Long 或完整机器人任务、训练及 A6。

## 图片和结构化证据

- [闭屉全景](OpenDrawer_scene_board.jpg)
- [闭屉同坐标近景](OpenDrawer_drawer_board.jpg)
- [开屉全景](PickCharger_scene_board.jpg)
- [开屉同坐标近景](PickCharger_drawer_board.jpg)
- [屉内 Charger](PickCharger_charger_board.jpg)
- [插座与 Charger 全景](InsertPlug_scene_board.jpg)
- [插座壳面近景](InsertPlug_socket_board.jpg)
- [Charger 壳体及双插脚](InsertPlug_charger_board.jpg)
- [失败方向的同坐标前后图](InsertPlug_A5_env0_charger_position.jpg)
- [检查、运行文件哈希与原帧索引](checks.json)
