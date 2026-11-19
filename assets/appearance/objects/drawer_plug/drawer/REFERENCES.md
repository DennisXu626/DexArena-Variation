# 材料依据与制作边界（抽屉／插座共用参考说明）

状态：下表为 2026-11-17 的历史准备。插座沿用已有结果；抽屉返工见下方最新方案。
以下是材质类别／工艺参考，不是实物的精确色度、BRDF测量或品牌复刻。

| 对象／方案 | 真实依据 | 本轮采用的细节 |
|---|---|---|
| 抽屉 warm_white | [IKEA MALM白色三抽柜](https://www.ikea.com/ch/en/p/malm-chest-of-3-drawers-white-20403562/)、[MALM材料表](https://www.ikea.com/my/en/p/malm-chest-of-6-drawers-white-70354644/)：人造板、丙烯酸涂装 | 暖白不透明涂层，适中哑光；表面没有透出的木纹与木材凹凸。保留当前模型的把手／滑轨，参考只约束板面，不复制MALM无把手造型。 |
| 抽屉 neutral_grey | [EGGER U708 ST9 Light Grey官方材料页](https://www.egger.com/en/furniture-interior-design/decors/U708_9)：中性浅灰、Smoothtouch Matt；有层压板／饰面板与配套封边产品 | 浅灰哑光覆面，板面与边缘统一；比白色涂装更粗糙。无木纹、无假划痕，不声称模拟肉眼难辨的微观压纹。 |
| 插座 warm_white | [Legrand Mallia Senses白色插座](https://www.legrand.ae/en/catalog/products/mallia-senses-socket-outlet-switched-1-gang-13-250-v-white-281111)：PC前盖、哑光 | 暖白不透明绝缘塑料，金属度0；沿用真实建模孔洞与暗色内衬，不复制参考产品的开关或孔型。 |
| 插座 neutral_grey | [Legrand国际插座官方技术表 F01897EN](https://assets.legrand.com/pim/NP-FT-GT/F01897EN-01.pdf)：聚碳酸酯、Anthracite／White等颜色 | 炭黑细哑光PC，金属度0，保留深孔及壳体边界；不将孔洞画在平面上。 |

检索日期2026-11-17。参数为渲染初始估计，不是厂家给定物理或PBR参数。
暖白／浅灰／炭黑在同光照任务图下是否足够可辨、是否出现过亮高光，须下轮人工复核。

## 2026-11-19 · 抽屉按部件返工

- **方案 A（浅橡木与暖白，ID `warm_white`）**：[UMAGE Treasures oak / White Sands](https://umage.com/collections/furniture/products/treasures-dresser?variant=50979061924174)。借鉴三层重复的浅橡木抽面、浅暖白侧围和深色拉手点缀。参考台面为橡木、侧围带织物；本方案按验收要求改成暖白哑光台面与侧板、浅灰内箱、黑色粉末喷涂金属把手，保留模型已有把手形状。
- **方案 B（浅灰与石墨色，ID `neutral_grey`）**：[Turri Blues 三抽柜](https://turri.it/product/blues-chest-of-drawers/)，[产品技术页（Light Gold 把手）](https://cassoni.com/wp-content/uploads/2024/09/cas-tur-blues-dresser-01-ds.pdf)。借鉴台面和柜壳分材质、整组三片抽面统一浅色饰面，以及低调浅金属小把手。参考款可用木、皮或石材；本方案采用指定的石墨耐磨覆面、中灰侧板、浅暖灰抽面和米白内箱，香槟把手采用低光泽金属表达。没有复制石纹或皮纹。
- A 仅在三片外抽面使用模型自带木纹，在线性空间轻柔降饱和、提亮冷色通道，保留所有原 UV、纹向与相对纹理起伏；原图保持只读。B 的平滑覆面及 A 的暖白板用纯色，保留原 alpha。两款滑轨沿用原像素、参数及绑定。
- 产品图只作参考。未下载或复制商品图、商标、纹理，也未新增几何、UV、碰撞或法线贴图。数字参数是待渲染验证的材质表达，不是厂家参数。闭合与开屉两组三列实景均待新授权。

## 图像、纹理与许可

- 上述官网图片只通过链接作为设计参考；没有下载、复制或发布其产品图片、商标、扫描纹理。
- 本轮没有发布新的外部纹理。抽屉候选色图由[适配器](../../../../../tasks/drawer_plug/fixture_appearance.py)按唯一[catalog](../../../../../tasks/assets/variation/drawer_plug/fixtures_v1/catalog.json)生成常量像素：原图尺寸/格式/alpha不变，原色图只读；原版恢复原像素。不是把木纹染色。
- 源资产仅有map_Kd，没有法线、粗糙度、金属度贴图；候选不增加这些贴图。遇到不符合该事实的运行资产会明确报错，不假定木材凹凸已经消除。
- 原模型／UV／纹理受原[资产许可](../../../../../tasks/assets/README.md)约束，不随本PR复制。自制色板与代码采用仓库[许可证](../../../../../LICENSE)。
- [历史色板](material_board.png)属于前版设计，不是任务效果图；新的抽屉平面色板可由[脚本](../../../../../tools/variation/make_drawer_socket_board.py)单独生成，不覆盖历史色板。

## RoboDojo：参考什么、采用什么

[官方论文v1](https://arxiv.org/html/2607.04434v1) §4.1.2与附录F.2描述：从真实物体参考／已有资源构建数字资产，保留语义与操作部件注释，并在实际模拟器中人工检查资产。F.1说明配置与运行分开、由seed控制采样。这里仅借鉴这套资产质量流程，不迁入Isaac Sim／USD或其物理设置。

实际读取官方代码固定提交 `fbfbbcb3801397fa00dcffaef3ca64d97c3fe76f`：

- [layout_manager.py](https://github.com/RoboDojo-Benchmark/RoboDojo/blob/fbfbbcb3801397fa00dcffaef3ca64d97c3fe76f/env/scene_manager/layout_manager.py) 的 `_randomize` 相关材质目录处理（约342–388行）：材质文件目录与对象visual配置分离，选择具体USD／MDL资源。
- [geometry.py](https://github.com/RoboDojo-Benchmark/RoboDojo/blob/fbfbbcb3801397fa00dcffaef3ca64d97c3fe76f/env/scene_manager/objects/geometry.py) `_apply_visual_material`（167–194行）：将独立材质资源绑定到对象及Mesh／GeomSubset。
- [table.py](https://github.com/RoboDojo-Benchmark/RoboDojo/blob/fbfbbcb3801397fa00dcffaef3ca64d97c3fe76f/env/scene_manager/objects/table.py) 初始化独立材质路径并绑定MDL；本轮不改桌面或使用其素材。

落地为：产品／材料参考 → URDF语义网格映射 → 唯一运行catalog → 环境私有材质／稳定纹理 → 独立可复现选择 → 待批准的实际SAPIEN图像人工审查。没有照搬全对象统一绑定，也没有将RoboDojo的物理材质修改带入本项目。

Cabinet [PR #10](https://github.com/DennisXu626/DexArena-Variation/pull/10)核对时仍开放、未合并，head `a029a74e1309b5772f74e21e5b9a4e1d7a6b5602`。仅参考已报告的“首次渲染前绑定稳定私有纹理，reset上传像素”方法；不依赖其分支，不带入Cabinet生产文件、色图或状态结论。
