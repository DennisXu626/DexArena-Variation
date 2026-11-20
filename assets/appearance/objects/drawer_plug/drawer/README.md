# 抽屉柜（drawer_plug.drawer）

**已按真实部件返工，[开、闭两组任务实景与工程复测](../../../../../docs/variation/evidence/drawer_socket/runtime_003/README.md)通过，Dennis 已确认两套外观。** [上轮任务实景与工程证据](../../../../../docs/variation/evidence/drawer_socket/runtime_002/README.md)记录旧配色。插座沿用旧结果。

PartNet Mobility 45841。[绑定表](bindings.json)逐项记录 47 个 URDF 视觉网格及 OBJ/MTL 绑定，附 96 个原资产文件的 SHA256。原几何、UV、任务初始化及物理行为不动。

| 部件 | 网格数量 | A · 浅橡木与暖白 | B · 浅灰与石墨色 |
|---|---:|---|---|
| 台面和前沿 | 1+1 | 暖白哑光 | 深石墨耐磨覆面 |
| 柜体侧板／背底及横梁 | 4+5 | 暖白 | 中灰 |
| 三片外抽面 | 3 | 原 UV 浅橡木纹、统一饰面 | 浅暖灰哑光 |
| 内箱前衬／侧／背／底 | 3+6+3+6 | 浅灰 | 米白 |
| 把手 | 9 | 黑色细哑光喷涂金属 | 低光泽香槟色金属 |
| 滑轨 | 6 | 原状 | 原状 |

台面为 `original-13.obj`。`original-12.obj` 虽在顶层抽面语义下，几何位置和台面前沿吻合，跟台面走；三片独立无 UV 内衬 `25/41/57` 跟内箱走。三个抽面 `18/34/50` 采用同一饰面和原 UV；没有给中层额外标记。

唯一参数源：[catalog](../../../../../tasks/assets/variation/drawer_plug/fixtures_v1/catalog.json)，抽屉记录 `drawer_revision=component-materials-v2`，沿用原方案 ID。显式 original 恢复原参数及原像素。同图不同角色分别绑定稳定私有纹理，局部 reset 上传像素；滑轨不绑定变体色图。

[产品依据](REFERENCES.md) · [用法与验收范围](../../../../../docs/variation/DRAWER_SOCKET_APPEARANCE.md) · [检查脚本](../../../../../tools/variation/check_drawer_socket.py)。只复测 OpenDrawer、PickCharger；插座不适用。Long 的抽屉也沿用该目录，但这次不追加 Long 渲染、完整任务、训练、A6 或规模化验证。
