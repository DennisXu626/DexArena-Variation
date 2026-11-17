# 抽屉柜（drawer_plug.drawer）

**素材参数、映射和接入已准备；未运行，真实感与A4/A5待验证。** 不计入已验收对象。

PartNet Mobility 45841；原UV/几何不变。本机静态资产HF revision `b197a198fe50f41d70f563cfa7c88d3cc9f528b6`；[bindings](bindings.json)列出URDF、47 OBJ、47 MTL、1 JPG逐文件SHA256，共99,044字节。这不代表未来服务器资产已经匹配。

- link_0为柜架/侧背底顶板/横梁，link_1/2/3为三层抽屉。32个板件视觉网格归panel；15个把手/滑轨归hardware，保留原版。
- 按URDF语义和OBJ文件绑定，不按贴图存在或重复MTL名分类。三层板面、可见内侧和边缘同设计，中层无特殊染色或提示标记。
- original恢复被改参数与原像素。warm_white为暖白丙烯酸涂装；neutral_grey为浅灰哑光层压覆面，均为木质基材上的不透明覆面，不是染色木纹冒充塑料。
- 源材质只有map_Kd；部分网格有UV，没有法线/粗糙度/金属度贴图。常量候选色图替换木纹颜色，保留alpha/UV。不新增噪声、划痕或UV，也不分发原纹理。
- 首次渲染前绑定逐环境私有稳定色图，reset只上传像素；原图只读。发现跨环境/语义材质共享或未知通道时报错。

唯一参数源：[catalog](../../../../../tasks/assets/variation/drawer_plug/fixtures_v1/catalog.json)。[真实参考、来源与制作说明](REFERENCES.md)、[平面色板](material_board.png)（非任务图）。

实际加载OpenDrawer、PickCharger、Long；InsertPlug不适用。单一原生表示，开合和Long阶段复用同组link；运行显示尚未验证。

[接口与运行提案](../../../../../docs/variation/DRAWER_SOCKET_APPEARANCE.md)、[检查脚本](../../../../../tools/variation/check_drawer_socket.py)、[固定配置](../../../../../examples/variation/drawer_plug/fixtures/fixed.json)、[原任务](../../../../../tasks/drawer_plug/drawer_plug_long.py)、[资产说明](../../../../../tasks/assets/README.md)、[总索引](../../../README.md)。历史V1调查代码e7d5c49只为静态归档，不是候选效果证据。完整任务/训练/A6未验证。
