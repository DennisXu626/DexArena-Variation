# Visual fix 001：诊断停止，正式修复未验证

本轮运行冻结提交 `ddc10c02c40cd149906122daf690d3325d6f4ccc`；作业88509，FAILED/1:0，13单卡分配秒，Requeue=0、Restarts=0。PR #10仍为草稿，待Dennis审验，未合并。旧作业88174的v1.1限定通过项保留为历史，不能作为v1.2运行通过证据。

## CPU证据与最小修复

当前安装SAPIEN3.0.3的default/gbuffer.frag第57–61行在textureMask含颜色纹理时直接采样colorTexture，否则才使用baseColor；minimal/default另一遍等已读着色器也如此。源码路径、片段和SHA见[结构化证据](results.json)。这证明相关着色器没有texture×baseColor调色机制；**实际运行中的可见材质绑定和更新尚未完全证实，不能宣布唯一根因已确定。**

仅修改原[适配器](../../../../../tasks/cabinet_pouring/variation.py)的预加载/应用路径，为柜体与碗换成保留原图明暗细节的派生配色贴图；original/violet完整恢复原属性与原贴图。参数仍取[唯一catalog](../../../../../tasks/assets/variation/cabinet_pouring/v1/catalog.json)现有ocean/citrus颜色，版本v1.2；瓶/盖参数、几何、UV、物理、机器人与位置规则不变。

[CPU制作脚本](../../../../../tools/variation/make_cabinet_tints.py)和[来源/哈希](../../../../../tasks/assets/variation/cabinet_pouring/v1/object_tints/provenance.json)记录12张PNG、3,896,904字节的可复现派生过程：原RGB明度×现有颜色，原alpha保留。原资产只读，不复制原图，派生资源沿用原PartNet/RoboCasa资产许可。复现命令（仅CPU，输出目录必须尚不存在）：

```bash
python -B tools/variation/make_cabinet_tints.py --assets /path/to/cabinet_pour --catalog tasks/assets/variation/cabinet_pouring/v1/catalog.json --output /private/new_tints
```

## 实际诊断失败

OpenCabinet单环境先记录原版，然后对link_0首个cabinet材质（首visual original-34.obj）做同相机/光照单变量探针。写不同base_color但保留贴图时画面相同；去掉该材质贴图后画面仍未变化，触发“Selected material is not visibly used by this surface”断言退出。失败保留，没有删除断言，也没有现场改库或把getter当视觉通过。该结果无法排除选中面不可见、绑定或更新问题。

| 已有图 | 含义 |
|---|---|
| [原版](DIAGNOSTIC_OpenCabinet_original_human_0.png) | 真实任务诊断实例初始画面 |
| [旧标量路径](DIAGNOSTIC_OpenCabinet_old_scalar_path_human_0.png) | 只改所选原材质参数 |
| [带贴图magenta](DIAGNOSTIC_OpenCabinet_magenta_with_native_texture_human_0.png) | 单变量诊断颜色，不是正式方案 |
| [去贴图magenta](DIAGNOSTIC_OpenCabinet_magenta_without_texture_human_0.png) | 诊断仍无可见变化，故停止 |

这些图**不是修复后方案实景**。没有原生柜体/碗的修复后original/ocean/citrus图，也没有独立珠子诊断图；不能借用历史图补齐。正式四短任务2env、Long1env以及瓶/盖/位置回归本轮全部未运行。

独立珠子场景的脚本已准备，复用原生build_sphere/Actor.merge和相同PilotVariation：在单独实例把原半径颗粒置于近距镜头前，瓶体留在视野外；正式任务颗粒位置/透明度不改。计划记录蓝/橙/紫、恢复及双env视觉隔离，并明确标注独立诊断，**本轮未到达该步骤**。

698源码+627原资产运行后哈希匹配，依赖身份保持；原PGID及队列watcher已退出，本线队列无遗留。全根采样含历史：峰值297,677,035字节，最终297,678,794；日志1,759字节。768MiB仍是可越限采样停止，跨PGID和全部驱动写盘边界未证明。第二次提交准备在安全时间门槛前未就绪，未再次提交，不将剩余287秒视为下轮授权。

后续需先有依据地定位实际可见表面/材质更新，再由Dennis确认短检窗口。没有机器人完整任务、训练或A6结论；对象验收计数不增加。
