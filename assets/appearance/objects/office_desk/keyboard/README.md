# 键盘 13106

`original` 恢复捕获的原生材质；`ochre_matte / indigo_satin` 的参数见 [catalog](catalog.json)。[绑定](bindings.json) 保护 77 个键帽及文字、原贴图、按键边界和目标键标记。

候选修改三个无纹理壳体槽及 `original-80/material_0_0` 内 76 个无字壳带三角面。该壳带通过连续 UV 与实际双线性采样的 [安全证明](key_uv_protection.json)，每个环境预先绑定一张私有纹理。候选上传目录色；`original` 上传逐字节相同的原生像素。其余 426 面及可动键保留原 PBR 和原纹理，顶点、法线、UV 和绕序不变。

TypeKeys 使用原 `mobility.urdf`，目标键 `P39/A24/I41/R45/ENTER35` 不变。原模型不随仓库提交。见 [运行与验收](../../../../../docs/variation/OFFICE_DEVICES_APPEARANCE.md)。
