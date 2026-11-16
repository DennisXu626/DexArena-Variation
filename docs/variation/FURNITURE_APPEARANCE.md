# Furniture Assembly四对象外观

四对象素材与真实任务预览已完成，用户已确认两套候选及original恢复正常，见[人工记录](../../assets/appearance/furniture_assembly/previews/author_check_20261116/human_review.json)。本包仅供外观制作与单环境CPU物理／SAPIEN GPU渲染初态预览，reset后无物理步进；不改任务源码、几何、碰撞或物理参数。正式任务配置、随机／回合记录、并行reset和A4／A5仍由Dennis后续组织。

## 1. 对象与部件

| 对象 | 当前真实表示 | 修改与保留 | 档案 |
|---|---|---|---|
| 板件 | LayFlatPanel动态Actor；另两任务固定Actor | 改主面、槽底、封边、槽口饰条；保留标签／条码 | [flat_panel](../../assets/appearance/objects/furniture_assembly/flat_panel/README.md) |
| 导向架 | 仅LayFlatPanel的rack Actor | 改主体／底板；保留垫片、螺栓、黄条 | [panel_rack](../../assets/appearance/objects/furniture_assembly/panel_rack/README.md) |
| 导轨 | rail_body link；两任务分别核定 | 改金属主体／槽唇；排除screw_head | [rail](../../assets/appearance/objects/furniture_assembly/rail/README.md) |
| 螺钉 | InsertRail十字头；FastenScrew翼形头 | 改主要头部；保留十字槽几何／金色顶帽或黄铜杆／方向顶条 | [screw](../../assets/appearance/objects/furniture_assembly/screw/README.md) |

每对象bindings记录源码角色、实际任务表示与保护边界；实际shape／part和材质读回见当前任务evidence。索引不是按shape序号绑定的规则。

## 2. 两套方案

[preview_set.json](../../examples/variation/furniture_assembly/preview_set.json)只映射统一方案名；各对象catalog是唯一参数源。

| 唯一catalog | variant_1 | variant_2 |
|---|---|---|
| [板件](../../assets/appearance/objects/furniture_assembly/flat_panel/variants/v1/catalog.json) | ivory_matte：浅象牙哑光 | navy_satin：深蓝表面 |
| [导向架](../../assets/appearance/objects/furniture_assembly/panel_rack/variants/v1/catalog.json) | 深蓝钢架／深色底板 | 浅灰白钢架／中灰底板 |
| [导轨](../../assets/appearance/objects/furniture_assembly/rail/variants/v1/catalog.json) | 深蓝金属／深蓝槽唇 | 香槟铜金属／深铜槽唇 |
| [螺钉](../../assets/appearance/objects/furniture_assembly/screw/variants/v1/catalog.json) | 深青头部 | 砖红头部 |

original恢复当前实例捕获的原生材质。候选仅改授权角色的base color、roughness和metallic，其余材质字段保留；无新增贴图、UV、模型或字体。原程序模型与署名按[LICENSE](../../LICENSE)保留，其它资源遵守[原资产许可](../../tasks/assets/README.md)。

## 3. 当前真实对照与记录

最终审阅源为家族归档，实际运行身份与结果见[summary](../../assets/appearance/furniture_assembly/previews/author_check_20261116/summary.json)。每张比较图左至右为original／variant_1／variant_2；同组使用同一reset、相机和光照。全景复用原任务human相机；近景仅换固定相机，不移动物体或关节。

| 任务与对象shape数 | 全景／对象近景 | 运行记录 |
|---|---|---|
| LayFlatPanel：板22、架32 | [全景](../../assets/appearance/furniture_assembly/previews/author_check_20261116/LayFlatPanel/comparison_task.png) · [板](../../assets/appearance/furniture_assembly/previews/author_check_20261116/LayFlatPanel/comparison_flat_panel.png) · [架](../../assets/appearance/furniture_assembly/previews/author_check_20261116/LayFlatPanel/comparison_panel_rack.png) | [manifest](../../assets/appearance/furniture_assembly/previews/author_check_20261116/LayFlatPanel/manifest.json) · [evidence](../../assets/appearance/furniture_assembly/previews/author_check_20261116/LayFlatPanel/evidence.json) |
| InsertRail：板22、轨25、钉21 | [全景](../../assets/appearance/furniture_assembly/previews/author_check_20261116/InsertRail/comparison_task.png) · [板](../../assets/appearance/furniture_assembly/previews/author_check_20261116/InsertRail/comparison_flat_panel.png) · [轨](../../assets/appearance/furniture_assembly/previews/author_check_20261116/InsertRail/comparison_rail.png) · [钉](../../assets/appearance/furniture_assembly/previews/author_check_20261116/InsertRail/comparison_screw.png) | [manifest](../../assets/appearance/furniture_assembly/previews/author_check_20261116/InsertRail/manifest.json) · [evidence](../../assets/appearance/furniture_assembly/previews/author_check_20261116/InsertRail/evidence.json) |
| FastenScrew：板22、轨14、钉4 | [全景](../../assets/appearance/furniture_assembly/previews/author_check_20261116/FastenScrew/comparison_task.png) · [板](../../assets/appearance/furniture_assembly/previews/author_check_20261116/FastenScrew/comparison_flat_panel.png) · [轨](../../assets/appearance/furniture_assembly/previews/author_check_20261116/FastenScrew/comparison_rail.png) · [钉](../../assets/appearance/furniture_assembly/previews/author_check_20261116/FastenScrew/comparison_screw.png) | [manifest](../../assets/appearance/furniture_assembly/previews/author_check_20261116/FastenScrew/manifest.json) · [evidence](../../assets/appearance/furniture_assembly/previews/author_check_20261116/FastenScrew/evidence.json) |

记录覆盖实际绑定、逐part材质、保护项及状态／几何／物理／UV／关节快照、原版材质和图像恢复；11个固定视角的恢复RGB最大差为0。版本、种子、源码／参数哈希、相机和捕获路径以各manifest为准；这些是初态作者检查，不是完整动力学或机器人任务成功结论。

## 4. 复现与查看

在已配置的独立Python环境、仓库根目录运行；输出须用新目录。任务名可选LayFlatPanel、InsertRail、FastenScrew。

```powershell
python tools/variation/render_furniture_preview.py --static
python tools/variation/render_furniture_preview.py --task LayFlatPanel --output outputs/furniture_preview/run_004/LayFlatPanel
python tools/variation/render_furniture_preview.py --task FastenScrew --view --scheme original --focus screw
```

1／2／3切换该任务全部本组对象的original／两候选；V循环固定全景和物体近景。focus只改变相机。组内不拖镜头，若挪动则按V恢复固定视角后重拍。用户已完成标签／条码、垫片／黄条、导轨槽唇、两种螺钉轮廓与参照、原版恢复检查；人工反馈单列，不冒充已收到人工截图。

## 5. 归档与交接

当前003证据采用 `furniture-evidence-compact-v1`：materials／meshes保存唯一profile，data保留全部原记录结构，以 `$ref` 引用重复值；不是仅保留摘要。下列工具可展开并校验完整原始capture字节SHA，或还原完整原文件，无需重复存一份JSON：

```powershell
python tools/variation/compact_furniture_evidence.py verify assets/appearance/furniture_assembly/previews/author_check_20261116/LayFlatPanel/evidence.json
python tools/variation/compact_furniture_evidence.py expand assets/appearance/furniture_assembly/previews/author_check_20261116/LayFlatPanel/evidence.json --output outputs/furniture_preview/LayFlatPanel_full.json
```

实际回归身份见manifest／summary。[59fb134完整历史归档](https://github.com/DennisXu626/DexArena-Variation/tree/59fb134f908f037c94caf5a018b1c6f13374caa0/assets/appearance/furniture_assembly/previews/author_check_20261116)保留旧002，早期单板件历史入口见板件档案；历史结果不改写。最终人检反馈独立记录。

完整baseline快照、个人环境和大输出不入库。对象总清单保持待正式接入验收；未覆盖Long、其它手型、GPU多环境隔离、随机流复现、任务判定完整回归或训练。分工与提交流程见[TEAM_APPEARANCE](TEAM_APPEARANCE.md)和[CONTRIBUTING](../../CONTRIBUTING.md)。
