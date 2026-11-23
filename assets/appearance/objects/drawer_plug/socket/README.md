# 插座（drawer_plug.socket）

**两套插座外观已通过 InsertPlug 双环境限定验收。** 原版、暖白及炭黑 PC 的同条件实景、原版恢复和局部 reset 隔离见[作业 121640](../../../../../docs/variation/evidence/drawer_socket/runtime_002/README.md)。

原生程序模型：六个碰撞/视觉盒体构成板壳和真实盲孔，两片独立暗色内衬只参与视觉。[bindings](bindings.json)列明构建顺序。不新增孔洞或把孔画在平面上。

- original保留原任务银色金属渲染；原物理接触材质hard_plastic不变，渲染与物理材质严格分开。
- warm_white为暖白哑光PC；neutral_grey为炭黑细哑光PC。只改六片shell，金属度0；两片hole保持原参数。
- 无导入UV/贴图，无新贴图、法线或几何；平滑PC用一致底色与粗糙度表达，不强加噪声。
- 复用原Charger逐环境builder材质复制方法；reset只改选中环境，Charger插脚不在此绑定集合。

唯一参数源：[catalog](../../../../../tasks/assets/variation/drawer_plug/fixtures_v1/catalog.json)。[产品参考与许可](../drawer/REFERENCES.md)、[平面色板](../drawer/material_board.png)（非任务图）。

实际加载InsertPlug、Long；OpenDrawer/PickCharger不适用。作业 121640 覆盖 Long 单环境阶段 reset；抽屉返工后的作业 121691 只覆盖两个抽屉短任务。[用法与验证范围](../../../../../docs/variation/DRAWER_SOCKET_APPEARANCE.md)、[联合配置](../../../../../examples/variation/drawer_plug/fixtures/combined.json)、[原任务](../../../../../tasks/drawer_plug/drawer_plug_long.py)、[总索引](../../../README.md)。炭黑款的两个插孔可辨，指尖遮住部分孔缘；当前光照下的高光差异无法定量。完整插入、训练和 A6 未验证。

## 十套家族外观

[十行映射、部件材料和实物参考](../../../../../docs/variation/DRAWER_TEN_VARIANTS.md)。新增选型已接入短任务并完成 CPU 核对，实际渲染和运行验收待补。既有已验收方案继续引用原 catalog。
