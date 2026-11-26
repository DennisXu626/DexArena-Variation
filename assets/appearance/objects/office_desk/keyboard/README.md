# 键盘 13106

[壳体与装饰边饰面](catalog.json) 和 [可动键帽饰面](keycaps_catalog.json) 各有原版与十套候选。壳体沿用 `office_devices_appearance`。`office_keyboard_appearance` 可独立加载 77 个原生可动键帽的材质，分别对主键区、外缘功能键和导航键着色。

[壳体绑定](bindings.json) 使用三个无纹理槽和 76 个无字装饰边三角面。装饰边沿用 [原 UV 安全分区](key_uv_protection.json)，各环境使用私有贴图。`original` 恢复捕获的 PBR 和逐字节原生像素。其余 426 面保护。

[键帽绑定](keycaps_bindings.json) 保留原字标轮廓、采样器、UV、几何和绕序。启用时，每个环境持有主键与功能键的两份私有贴图，切换时在同一句柄更新像素，`original` 逐字节恢复原贴图。目标键 P、A、I、R、Enter 的映射及绿色指示标记沿用原任务。见 [Office Desk 外观](../../../../../docs/variation/OFFICE_DEVICES_APPEARANCE.md)。
