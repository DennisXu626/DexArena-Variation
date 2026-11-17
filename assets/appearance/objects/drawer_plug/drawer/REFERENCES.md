# 材料依据与制作边界（抽屉／插座共用参考说明）

状态：设计与CPU接入准备；**没有实际任务渲染，真实感尚待人工验收**。
以下是材质类别／工艺参考，不是实物的精确色度、BRDF测量或品牌复刻。

| 对象／方案 | 真实依据 | 本轮采用的细节 |
|---|---|---|
| 抽屉 warm_white | [IKEA MALM白色三抽柜](https://www.ikea.com/ch/en/p/malm-chest-of-3-drawers-white-20403562/)、[MALM材料表](https://www.ikea.com/my/en/p/malm-chest-of-6-drawers-white-70354644/)：人造板、丙烯酸涂装 | 暖白不透明涂层，适中哑光；表面没有透出的木纹与木材凹凸。保留当前模型的把手／滑轨，参考只约束板面，不复制MALM无把手造型。 |
| 抽屉 neutral_grey | [EGGER U708 ST9 Light Grey官方材料页](https://www.egger.com/en/furniture-interior-design/decors/U708_9)：中性浅灰、Smoothtouch Matt；有层压板／饰面板与配套封边产品 | 浅灰哑光覆面，板面与边缘统一；比白色涂装更粗糙。无木纹、无假划痕，不声称模拟肉眼难辨的微观压纹。 |
| 插座 warm_white | [Legrand Mallia Senses白色插座](https://www.legrand.ae/en/catalog/products/mallia-senses-socket-outlet-switched-1-gang-13-250-v-white-281111)：PC前盖、哑光 | 暖白不透明绝缘塑料，金属度0；沿用真实建模孔洞与暗色内衬，不复制参考产品的开关或孔型。 |
| 插座 neutral_grey | [Legrand国际插座官方技术表 F01897EN](https://assets.legrand.com/pim/NP-FT-GT/F01897EN-01.pdf)：聚碳酸酯、Anthracite／White等颜色 | 炭黑细哑光PC，金属度0，保留深孔及壳体边界；不将孔洞画在平面上。 |

检索日期2026-11-17。参数为渲染初始估计，不是厂家给定物理或PBR参数。
暖白／浅灰／炭黑在同光照任务图下是否足够可辨、是否出现过亮高光，须下轮人工复核。

## 图像、纹理与许可

- 上述官网图片只通过链接作为设计参考；没有下载、复制或发布其产品图片、商标、扫描纹理。
- 本轮没有发布新的外部纹理。抽屉候选色图由[适配器](../../../../../tasks/drawer_plug/fixture_appearance.py)按唯一[catalog](../../../../../tasks/assets/variation/drawer_plug/fixtures_v1/catalog.json)生成常量像素：原图尺寸/格式/alpha不变，原色图只读；原版恢复原像素。不是把木纹染色。
- 源资产仅有map_Kd，没有法线、粗糙度、金属度贴图；候选不增加这些贴图。遇到不符合该事实的运行资产会明确报错，不假定木材凹凸已经消除。
- 原模型／UV／纹理受原[资产许可](../../../../../tasks/assets/README.md)约束，不随本PR复制。自制色板与代码采用仓库[许可证](../../../../../LICENSE)。
- [色板](material_board.png)由[脚本](../../../../../tools/variation/make_drawer_socket_board.py)生成，仅平面颜色示意，**不是任务效果图，也不能表达实际粗糙度／高光**。

## RoboDojo：参考什么、采用什么

[官方论文v1](https://arxiv.org/html/2607.04434v1) §4.1.2与附录F.2描述：从真实物体参考／已有资源构建数字资产，保留语义与操作部件注释，并在实际模拟器中人工检查资产。F.1说明配置与运行分开、由seed控制采样。这里仅借鉴这套资产质量流程，不迁入Isaac Sim／USD或其物理设置。

实际读取官方代码固定提交 `fbfbbcb3801397fa00dcffaef3ca64d97c3fe76f`：

- [layout_manager.py](https://github.com/RoboDojo-Benchmark/RoboDojo/blob/fbfbbcb3801397fa00dcffaef3ca64d97c3fe76f/env/scene_manager/layout_manager.py) 的 `_randomize` 相关材质目录处理（约342–388行）：材质文件目录与对象visual配置分离，选择具体USD／MDL资源。
- [geometry.py](https://github.com/RoboDojo-Benchmark/RoboDojo/blob/fbfbbcb3801397fa00dcffaef3ca64d97c3fe76f/env/scene_manager/objects/geometry.py) `_apply_visual_material`（167–194行）：将独立材质资源绑定到对象及Mesh／GeomSubset。
- [table.py](https://github.com/RoboDojo-Benchmark/RoboDojo/blob/fbfbbcb3801397fa00dcffaef3ca64d97c3fe76f/env/scene_manager/objects/table.py) 初始化独立材质路径并绑定MDL；本轮不改桌面或使用其素材。

落地为：产品／材料参考 → URDF语义网格映射 → 唯一运行catalog → 环境私有材质／稳定纹理 → 独立可复现选择 → 待批准的实际SAPIEN图像人工审查。没有照搬全对象统一绑定，也没有将RoboDojo的物理材质修改带入本项目。

Cabinet [PR #10](https://github.com/DennisXu626/DexArena-Variation/pull/10)核对时仍开放、未合并，head `a029a74e1309b5772f74e21e5b9a4e1d7a6b5602`。仅参考已报告的“首次渲染前绑定稳定私有纹理，reset上传像素”方法；不依赖其分支，不带入Cabinet生产文件、色图或状态结论。
