# 下一物体候选分析（不实施适配）

2026-11-15。仅从当前对象清单、当前main源码及已有V1本地缓存读取三个候选；没有下载、任务导入、仿真、渲染、素材制作或新运行配置。以下“已确认”是**源文件静态事实**，不是当前SAPIEN加载或材质隔离验证。三个对象仍为待适配，A6没有完成。

## 推荐与成本比较

| 候选 | 主要新增问题 | 初步非GPU工作量 | 首轮单卡GPU用量估计 |
|---|---|---|---|
| **推荐：Office Mouse 101408** | 外部URDF多link／多OBJ，源材质同名但角色不同，移动按钮／滚轮与每env绑定 | 4–6小时 | 300–600分配秒 |
| Dustpan | 外部GLB的PBR primitive与既有程序握套混合；碰撞CoACD加载成本 | 4–8小时 | 600–900分配秒 |
| Blender023 | MJCF多材质共用atlas、透明部件及按任务生成／合并的盖视觉 | 8–12小时 | 900–1800分配秒 |

以上是按源码路径、部件数量和预期检查量作的**粗估，不是实测、预算承诺或本轮授权**；包括最小接入、资料、原生对照、1／2env选择／记录／物理及原相机局部reset检查，不含训练或完整机器人任务。正式执行前需再确认完整资产、原生并行限制、既有缓存／依赖和一次性写盘位置；拟单次作业不超过10分钟、总额另批，确定性失败停止。没有把Charger的29秒外推成其它模型的性能指标。

推荐Mouse先只覆盖`OfficeDeskClickMouse-Sharpa-v1`：它比Charger增加外部URDF、分link材质和运动部件，且源材质无纹理／UV，能把流程复用的主要未知集中在真实部件绑定与每env隔离，避免首轮同时处理atlas和透明度。Long有独立加载路径且明确只支持1env，不将它偷偷迁入2env检查，不承诺首轮Long覆盖。

## 1. Office Mouse 101408（推荐）

**对象／任务／来源**：[对象档案](../../assets/appearance/objects/office_desk/mouse/README.md)；正式短任务[OfficeDeskClickMouseEnv](../../tasks/office_desk/office_desk_click_mouse.py)继承BaseEnv，不能按名字假定复用[OfficeDeskLongEnv](../../tasks/office_desk/office_desk_long.py)的加载函数。短任务在`_load_scene`按env循环构建`self._mice`；Long的`_load_mouse`另写一条路径，并在构造中拒绝num_envs≠1。

**资产可定位及静态事实**：`tasks/assets/task_object_meshes/office/101408/mobility.urdf`，缓存URDF SHA256 `3ba86480405df628e357b9c9ddf0913de5239c763aa3d84fca893f38db4ac038`。5个link：base、link_0…link_3；base无visual。link_0／1为两个按钮（prismatic），link_2为滚轮（continuous），link_3为外壳（固定连接）。共5个OBJ visual引用：按钮original-3／4、滚轮original-5、外壳original-2／1。

这5个实际OBJ均为**0个vt**，各使用名为material_0_0的槽；各MTL有原生Kd／不透明参数，没有map_Kd。灰色值并非全相同，**不能因同槽名把不同文件的材质合并**；目录名textured_objs不表示这些模型有贴图／UV。短任务加载原mobility.urdf、scale=.08、fixed root，原按钮／轮子的drive、摩擦及碰撞配置须保留；已有mobility_planar_mouse.urdf文件不等于任务正在用它。

**拟最小方法与修改范围（尚未做）**：在短任务真实loader／builder处识别每env、每link的外壳／按钮／滚轮视觉材料，先采用参数方案，保留按钮分界和轮廓。沿用现有固定／集合随机／回合记录模式，仅隔离可变渲染材质；不新增贴图、UV、几何或物理改写。不沿用Charger按box尺寸匹配的规则。未来拟改`office_desk_click_mouse.py`的构造／视觉绑定／reset接入及该物体专用小素材参数、示例／档案；不改其它Office任务或Long并行限制，不先建通用框架。

**主要未知与下阶段方法**：源OBJ数不等于SAPIEN render part数；URDF loader是否在不同link／env共享material、实际按钮可见性、CoACD既有缓存／耗时尚未知。需遍历每env articulation的实际link渲染体；空base或根articulation没有RenderBody不能被误判为整个鼠标无视觉。下阶段先在原生1env读实际link／part绑定与碰撞／质量／drive状态；再在已批预算内2env检查选中重选与未选状态／原RGB隔离，验证按钮qpos／点击判定不受外观影响。Long如以后纳入，单独按其真实单环境路径验收，不能用短任务通过代替。

## 2. Table Cleaning Dustpan

**对象／任务／源码**：[对象档案](../../assets/appearance/objects/table_cleaning/dustpan/README.md)，`TableCleaningPickDebris-Sharpa-v1`与`TableCleaningDumpDustpan-Sharpa-v1`使用[TableCleanBase及build_dustpan](../../tasks/table_cleaning/table_cleaning_long.py)，DumpDustpan实际继承该base；Long同家族存在但不自动纳入下一轮验收。

**资产与静态事实**：`tasks/assets/task_object_meshes/TableClean/glb_cache/21901bdd81f649e89af087ae6f67ca7e.glb`，SHA256 `6ab8d568b3c1d05edd74958d694d13f43f0e1ade2ff2444820d172e860b4a061`，当前缓存18168字节。GLB为glTF2，3个primitive、2个PBR材质black／blue-plastic，images和textures为空，没有TEXCOORD属性。它是外部模型，**不是带纹理atlas的模型**。

原生builder用同一GLB加载visual与CoACD碰撞，并额外加既有capsule握套visual／collision（程序深灰、roughness .9）；资产来源／许可说明位于任务源码注释（Objaverse UID，标注CC BY-SA 4.0），仍应按原来源获取，不复制模型进Git。

**拟方法、价值及范围**：以后只隔离／绑定外部GLB两类材料与程序握套，保持原scale／旋转、CoACD参数及握套几何，不为换色重建模型。可验证跨GLB/PBR导入与混合程序部件的同回合一致性。拟改现有`build_dustpan`视觉材料接入、该物体小参数／档案与短验证；不改碎屑、垃圾桶、物理或成功条件。

**未知与验证**：SAPIEN导入后是否合并primitive、实际part→源材质对应、黑色部件与握套是否共享材质、已有CoACD缓存及首载成本尚未运行确认。未来先读原生绑定及缓存，再核对visual／collision hash、质量、摩擦与物体初态；2env局部reset加原RGB隔离。若原生碰撞准备超过批准时限，保存原因停止，不以简化几何或改碰撞通过。

## 3. Juice Preparation Blender023

**对象／任务／源码**：[对象档案](../../assets/appearance/objects/juice_preparation/blender/README.md)，候选任务为[AppleToBlender](../../tasks/juice_preparation/juice_preparation_apple_to_blender.py)、[PlaceLid](../../tasks/juice_preparation/juice_preparation_place_lid.py)、[PressButton](../../tasks/juice_preparation/juice_preparation_press_button.py)。实际任务分别准备MJCF；PressButton额外调用`_integrate_lid_visual_into_blender`，AppleToBlender未执行这一盖视觉合并，不能把所有任务视为同一初始化表示。

**资产与静态事实**：`tasks/assets/task_object_meshes/juice/Blender023/model.xml`，SHA256 `b7f9249739f2355a58759abb020d5147af28633295ab04ae07494fe7b8b29f20`。读取到6个mesh／6个material：Body001、knob_speed、pitcher、blade、pitcher_main、power_button。6个OBJ均有vt；5个texture声明复用同一`visuals/T_BC001.png`，该图片缓存存在。pitcher_main材质无纹理、RGBA alpha=.75。源XML有按钮slide与旋钮hinge；不能据XML直接宣称当前SAPIEN透明效果／joint状态已核定。本次没有完整核对另一个lid包，不将本体UV结论套到盖。

**拟方法、价值及范围**：以后先针对一个正式任务，在已有MJCF准备之后定位实际部件，仅调整已核定底座／旋钮的渲染参数，保留透明罐／刀片和按钮参照；若替换共用atlas需另行审阅，不能自动覆盖全部5个声明。能验证MJCF转换、共用纹理与透明材质、任务间盖视觉表示差异。可能涉及现有blender资产加载／MJCF准备函数及选定子任务绑定、专用参数／档案；不修改按钮物理、碰撞或源共享资产。

**未知与验证**：运行准备产物真实落盘位置、loader映射／alpha处理、lid完整依赖、不同子任务实际加载部件及每env材质别名仍待确认。未来先做只读路径／依赖和写盘边界检查，再批准有总量上限的私有准备与1／2env小检；保持原UV、透明层及按钮运动，检查表示变化前后外观／状态隔离。因路径与多阶段复杂度高，首轮不推荐。

## 本轮证据与边界

源码核对基于PR #1整合后的main；上述任务源码相对上一轮main没有运行修改。资产仅是已存在V1缓存，来源参考HF revision `b197a198fe50f41d70f563cfa7c88d3cc9f528b6`；文件SHA只标识本次读到的文件，**不推断未来运行资产整包同一版本**。原模型／贴图／许可获取方式见[SETUP](SETUP.md)与[上游资源说明](../../tasks/assets/README.md)。

本地交付的CANDIDATE_ASSET_FACTS.json记录实际XML／OBJ／MTL／GLB结构与文件身份，读取辅助脚本只用标准库，不导入任务或renderer。没有为缺失信息下载大包或启动服务器，未生成任何候选材质、贴图、UV、几何、适配代码或运行配置；所有候选在对象清单中保持待适配。
