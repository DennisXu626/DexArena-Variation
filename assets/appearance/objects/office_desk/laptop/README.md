# 笔记本 10211

`original` 保留本次原生材质，`terracotta_matte / petrol_satin` 的唯一参数见 [catalog](catalog.json)。[绑定](bindings.json) 明确保护屏幕原图、底座、集成键盘、触控板、转轴和细节。

OpenLaptop 每环境 `_laptops[env_id]`，scale=.3；只改 `link_1.visual[2] / screen_frame-16 / new-2.obj` 的 `material-0`。按原生part私有复制，其他5个材质槽保护；无新增UV/纹理，不整OBJ覆盖。源材质组三角位置指纹、Kd和2414三角形共同核定身份，不依赖part顺序。

原资产 revision `b197a198fe50f41d70f563cfa7c88d3cc9f528b6`，282安装文件已核官方身份；URDF引用闭包166文件完整。模型不入Git。TypeKeys不加载laptop；Long未接入。[运行与验收边界](../../../../../docs/variation/OFFICE_DEVICES_APPEARANCE.md)。
