# 按物体组织的外观档案

这是**已有外观归档，不是新增运行能力**。每个稳定逻辑对象一个目录：十家族V1的40条对象记录全部保留，另补V2／M1的两个无视觉追溯项；不将157条逐任务初始化行变成157套素材。不同家族同名对象不凭名称合并；A／B／C阶段表示记录在bindings，不重复复制贴图。

已有新外观包括Cabinet瓶／盖的Ocean、Citrus、Violet配套三方案（已验收M2），以及Charger的ivory_matte、navy_satin、copper_metal（A1–A3材质与两任务各2env A4／A5已验收）；Mouse 101408的ivory_matte／navy_satin也已完成限定ClickMouse双环境验收（集成记录见[PR #6](https://github.com/DennisXu626/DexArena-Variation/pull/6)）；其余对象状态如下。目录数量不是适配完成度。无视觉bolt_platform、particle_support和liquid_state不要求生产皮肤；brush资源存在但当前任务未实例化；Charger档案已含正式接入与运行证据，但完整机器人任务成功和A6未验证。机器人、共享桌面／地面和背景扩展不在本轮，V2 shared_table行不建皮肤目录。

## 快速使用

1. 从[objects.csv](objects.csv)或下表进入某对象，先读状态／原资源／加载边界。
2. [Charger参数与接入证据](objects/drawer_plug/charger/README.md)引用唯一运行catalog；瓶／盖已有[参数、纹理、绑定、原版及任务对照](objects/cabinet_pouring/bottle/README.md)，盖[角度参照](objects/cabinet_pouring/bottle_cap/previews/README.md)为历史人工工程检查。
3. 查看[runtime_mapping.json](runtime_mapping.json)：对象目录是制作／归档入口，`tasks/assets/variation/cabinet_pouring/v1`是当前运行发布副本，Charger则引用现有`tasks/assets/variation/drawer_plug/v1/catalog.json`，不复制参数；档案本身没有新loader。修改档案后需适配验收再同步发布，两者不是可独立编辑的源，单边修改不算发布完成。
4. [Pillow制作说明](objects/cabinet_pouring/bottle/authoring/README.md)提供历史生成脚本的最小可移植版本；不默认覆盖发布素材，字体外部提供。瓶盖无UV／新贴图，不制造假textures或UV文件。

原版不是第四张自制贴图，选择original恢复捕获的原生材质。原OBJ／MTL／原纹理等第三方资源只引用来源和身份，不复制整包。瓶身UV直接属于原OBJ，未单独生成。瓶与盖当前成套scheme选择，不支持任意独立混配。

当前能力以[STATUS集中清单](../../docs/variation/STATUS.md)为准。Meal 的五个对象引用[唯一运行 catalog](../../tasks/assets/variation/meal_preparation/v1/catalog.json)，详见[用法](../../docs/variation/MEAL_APPEARANCE.md)和[PR #8](https://github.com/DennisXu626/DexArena-Variation/pull/8)。[三个候选的静态分析](../../docs/variation/OBJECT_CANDIDATES.md)不改变下表状态，也不代表A6完成。

## 对象与状态

按实际目录与CSV复核：42个对象、10家族；已验收限定试点14（原有4＋Meal5＋抽屉和插座2＋单门柜1＋碗和模拟液滴2）；待适配21；无视觉不适用3；当前未加载1；已实现待审验3；外部推进待验收0。Mouse仅保留既有ClickMouse限定验收；Meal依据[审验结论](https://github.com/DennisXu626/DexArena-Variation/pull/8#pullrequestreview-5919739591)标记为限定技术验收通过，待整合/合并；集成状态见[PR8](https://github.com/DennisXu626/DexArena-Variation/pull/8)。待适配仅表示未来入口，非本轮开发授权。

| 家族 | 对象目录 | 当前状态 |
|---|---|---|
| cabinet_pouring | [cabinet](objects/cabinet_pouring/cabinet/README.md) | 已完成限定试点（OpenCabinet／PickBottle，各 2 环境） |
| cabinet_pouring | [bottle](objects/cabinet_pouring/bottle/README.md) | 已完成试点（继承M2验收） |
| cabinet_pouring | [bottle_cap](objects/cabinet_pouring/bottle_cap/README.md) | 已完成试点（继承M2验收） |
| cabinet_pouring | [bowl](objects/cabinet_pouring/bowl/README.md) | 已完成限定试点（PourBeads，2 环境） |
| cabinet_pouring | [beads](objects/cabinet_pouring/beads/README.md) | 已完成限定试点（PourBeads，2 环境） |
| drawer_plug | [drawer](objects/drawer_plug/drawer/README.md) | 已完成限定试点（OpenDrawer／PickCharger，两套分件外观） |
| drawer_plug | [socket](objects/drawer_plug/socket/README.md) | 已完成限定试点（InsertPlug，暖白／炭黑 PC） |
| drawer_plug | [charger](objects/drawer_plug/charger/README.md) | 已完成限定试点（A1–A3已接受；两任务各2env A4／A5通过） |
| furniture_assembly | [flat_panel](objects/furniture_assembly/flat_panel/README.md) | 待适配 |
| furniture_assembly | [panel_rack](objects/furniture_assembly/panel_rack/README.md) | 待适配 |
| furniture_assembly | [rail](objects/furniture_assembly/rail/README.md) | 待适配 |
| furniture_assembly | [screw](objects/furniture_assembly/screw/README.md) | 待适配 |
| juice_preparation | [mini_fridge](objects/juice_preparation/mini_fridge/README.md) | 待适配 |
| juice_preparation | [apple](objects/juice_preparation/apple/README.md) | 待适配 |
| juice_preparation | [blender](objects/juice_preparation/blender/README.md) | 待适配 |
| juice_preparation | [blender_lid](objects/juice_preparation/blender_lid/README.md) | 待适配 |
| meal_preparation | [lunch_box](objects/meal_preparation/lunch_box/README.md) | 限定技术验收通过，待整合/合并；集成状态见PR8 |
| meal_preparation | [plate](objects/meal_preparation/plate/README.md) | 限定技术验收通过，待整合/合并；集成状态见PR8 |
| meal_preparation | [spoon](objects/meal_preparation/spoon/README.md) | 限定技术验收通过，待整合/合并；集成状态见PR8 |
| meal_preparation | [bread](objects/meal_preparation/bread/README.md) | 限定技术验收通过，待整合/合并；集成状态见PR8 |
| meal_preparation | [tomato](objects/meal_preparation/tomato/README.md) | 限定技术验收通过，待整合/合并；集成状态见PR8 |
| nut_bolt | [bolt](objects/nut_bolt/bolt/README.md) | 待适配 |
| nut_bolt | [nut](objects/nut_bolt/nut/README.md) | 待适配 |
| nut_bolt | [bolt_platform](objects/nut_bolt/bolt_platform/README.md) | 无视觉，不适用皮肤 |
| office_desk | [laptop](objects/office_desk/laptop/README.md) | 待适配 |
| office_desk | [keyboard](objects/office_desk/keyboard/README.md) | 待适配 |
| office_desk | [mouse](objects/office_desk/mouse/README.md) | 限定试点已验收（仅ClickMouse 2env A4／A5） |
| package_opening | [package](objects/package_opening/package/README.md) | 限定证据已查收，待PR9最终合并 |
| package_opening | [apple](objects/package_opening/apple/README.md) | 限定证据已查收，待PR9最终合并 |
| package_opening | [package_plate](objects/package_opening/package_plate/README.md) | 限定证据已查收，待PR9最终合并 |
| pipette_transfer | [pipette](objects/pipette_transfer/pipette/README.md) | 待适配 |
| pipette_transfer | [sample_cup](objects/pipette_transfer/sample_cup/README.md) | 待适配 |
| pipette_transfer | [test_tube](objects/pipette_transfer/test_tube/README.md) | 待适配 |
| pipette_transfer | [tube_rack](objects/pipette_transfer/tube_rack/README.md) | 待适配 |
| pipette_transfer | [pipette_stand](objects/pipette_transfer/pipette_stand/README.md) | 待适配 |
| pipette_transfer | [tip_cup](objects/pipette_transfer/tip_cup/README.md) | 待适配 |
| table_cleaning | [dustpan](objects/table_cleaning/dustpan/README.md) | 待适配 |
| table_cleaning | [bin](objects/table_cleaning/bin/README.md) | 待适配 |
| table_cleaning | [debris](objects/table_cleaning/debris/README.md) | 待适配 |
| table_cleaning | [brush](objects/table_cleaning/brush/README.md) | 当前未加载，不纳入必做皮肤 |
| cabinet_pouring | [particle_support](objects/cabinet_pouring/particle_support/README.md) | 无视觉，不适用皮肤 |
| pipette_transfer | [liquid_state](objects/pipette_transfer/liquid_state/README.md) | 无视觉，不适用皮肤 |

## 来源与验证边界

覆盖依据：已验收V1 OBJECT_APPEARANCE.csv（40条）与V2 OBJECT_INITIALIZATION.csv（157条）、M1 PILOT_ASSETS及实际视觉结构，代码调查基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8；原始调查表由维护者保管，不将个人本机路径或内部日志上传。V2 rail_screw映射rail／screw部件，integrated_blender_top映射blender／lid的实际合并分支，不虚构独立对象；tip_cup是stand部件，独立目录仅保留逻辑追溯。

[预览来源清单](preview_sources.json)记录M2历史图片原文件名、版本和SHA256。所有任务图均为历史SAPIEN实际渲染，本轮仅复制、解码和静态核对，没有GPU、仿真、重渲染、服务器连接或训练。平面标签文件不是任务应用效果。代码、HF选定素材revision与运行环境分别记载；V1静态模型图不能替代实际加载证据。

第三方模型、纹理和字体按原来源及许可获取，详见[SETUP](../../docs/variation/SETUP.md)、[资源说明](../../tasks/assets/README.md)及[LICENSE](../../LICENSE)。本轮不修改既有运行代码、运行catalog／PNG、M3 PR或协作规范。静态核对使用[最小检查脚本](../../tools/variation/check_appearance_archive.py)。

Meal 五对象依据[PR8-R2查收结论](https://github.com/DennisXu626/DexArena-Variation/pull/8#pullrequestreview-5919739591)标为 `accepted_pilot`，表示限定技术验收通过，待整合/合并；集成状态见[PR8](https://github.com/DennisXu626/DexArena-Variation/pull/8)。[PR8-R2证据索引](../../docs/variation/evidence/meal_preparation/PR8-R2.md)说明源码对应、复用范围和历史追溯限制。


Package三对象的接入和限定证据见[PR9-R2索引](../../docs/variation/evidence/package_opening/PR9-R2.md)，当前implemented_pending_review，不增加已验收计数。
