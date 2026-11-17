# 插座（drawer_plug.socket）

**两套材质参数与接入已准备；未运行，真实感/RGB/隔离待验证。** 不计入已验收对象。

原生程序模型：六个碰撞/视觉盒体构成板壳和真实盲孔，两片独立暗色内衬只参与视觉。[bindings](bindings.json)列明构建顺序。不新增孔洞或把孔画在平面上。

- original保留原任务银色金属渲染；原物理接触材质hard_plastic不变，渲染与物理材质严格分开。
- warm_white为暖白哑光PC；neutral_grey为炭黑细哑光PC。只改六片shell，金属度0；两片hole保持原参数。
- 无导入UV/贴图，无新贴图、法线或几何；平滑PC用一致底色与粗糙度表达，不强加噪声。
- 复用原Charger逐环境builder材质复制方法；reset只改选中环境，Charger插脚不在此绑定集合。

唯一参数源：[catalog](../../../../../tasks/assets/variation/drawer_plug/fixtures_v1/catalog.json)。[产品参考与许可](../drawer/REFERENCES.md)、[平面色板](../drawer/material_board.png)（非任务图）。

实际加载InsertPlug、Long；OpenDrawer/PickCharger不适用。单个原生表示，Long工程路径待验证。[接口与待批准计划](../../../../../docs/variation/DRAWER_SOCKET_APPEARANCE.md)、[联合配置](../../../../../examples/variation/drawer_plug/fixtures/combined.json)、[原任务](../../../../../tasks/drawer_plug/drawer_plug_long.py)、[总索引](../../../README.md)。孔内对比与高光质量必须用实景验收；完整插入、训练、A6未验证。
