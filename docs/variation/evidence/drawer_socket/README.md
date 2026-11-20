# 抽屉与插座外观验收证据

抽屉 A／B 的开闭实景由 Dennis 确认，覆盖 OpenDrawer 和 PickCharger；插座暖白／炭黑 PC 的验收覆盖 InsertPlug。Long 单环境阶段检查来自抽屉返工前的版本。

## 历次交付

准备阶段保存[CPU检查结果](cpu_preparation.json)与[文件身份](preparation_manifest.json)。GPU为0，没有实际任务图、物理运行、RGB隔离或真实感通过结论。

[材料参考与非任务色板](../../../../assets/appearance/objects/drawer_plug/drawer/REFERENCES.md)、[用法与验收范围](../../DRAWER_SOCKET_APPEARANCE.md)。此处的 CPU 结果用于追溯准备版本。

检查包括明确外观钩子以外完整任务AST一致、原Charger生产文件/catalog逐字节相同、源资产闭包hash、CPU色域/alpha及独立选择/回合记录、归档计数/链接。独立选择检查使用空材质绑定，**不作为真实绑定或A4/A5运行证据**。

原始本机报告与成本位于维护者交付 `deliverables/drawer_socket_appearance/`；不复制原模型、私有环境或运行缓存。

[运行续篇：作业 121613 原版实景与首个失败](runtime_001/README.md)。候选材质未运行，不是视觉验收。

[第二轮：抽屉／插座实景对照及作业 121640](runtime_002/README.md)。插座实景与工程短检通过，抽屉配色随后返工。

[第三轮：按部件返工后，抽屉开／闭实景与作业 121691](runtime_003/README.md)。插座沿用上一轮结果。
