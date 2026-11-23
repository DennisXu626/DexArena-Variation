# 移液器支架

支架是单个 kinematic Actor。其 47 个视觉由底板、立柱、导环和[吸头承托盘](../tip_cup/README.md)组成。十套候选分别配色，`visual[4]` 仍为独立配色的承托盘。见[参数目录](../catalog.json)与[绑定](bindings.json)。

[灰阶底板原稿](base-plate-mark.png)为本仓原创，含字样和细微喷涂颗粒，字样位于原生盒体顶面的 UV 区域。默认光栅管线直接采用色彩贴图中的颜色。[烘焙工具](../../../../../tools/variation/build_pipette_stand_textures.py)在色彩线性空间组合原稿与 catalog 底板色，再编码成各候选的不透明 sRGB PNG。运行工具可校验全部贴图像素，加入 `--write` 可按相同规则重新生成。original 恢复原生材质。

[任务验收与实景](../previews/runtime/summary.json) · [正式说明](../../../../../docs/variation/PIPETTE_APPEARANCE.md)
