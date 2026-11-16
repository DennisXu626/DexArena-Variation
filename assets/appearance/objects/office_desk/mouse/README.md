# 鼠标（model_id 101408）（office_desk.mouse）

状态：**限定范围已验收**。对象Mouse 101408，仅`OfficeDeskClickMouse-Sharpa-v1`的双环境外观及A4／A5；PR #6尚未合入main。下方历史候选/准备段落保留当时结论。

原始角色：可交互输入设备。V1资源说明：`assets/task_object_meshes/office/101408/mobility.urdf`。

原版original加ivory_matte／navy_satin两套外观，实际link_0/1按钮、link_2滚轮和link_3外壳已核对。只引用唯一运行catalog，不新增纹理、UV、几何或独立参数源；原静态图册本身仍不是加载证明。

## 资料与加载边界

V1对象键：`office_desk/mouse`；V2对应键：`office_mouse`。代码调查基准e7d5c49d079153e77da1ce2bfde16edf67ee7fa8；V1视觉资料HF revision b197a198fe50f41d70f563cfa7c88d3cc9f528b6，此revision只说明调查素材，不保证所有后续运行资产等同。

- fixed-root articulation visual/collision model

正式任务入口（保留家族区分，不凭同名合并）：OfficeDeskClickMouse-Sharpa-v1。

## 原始来源

- [tasks/office_desk/office_desk_long.py](../../../../../tasks/office_desk/office_desk_long.py)
- [tasks/office_desk/office_desk_click_mouse.py](../../../../../tasks/office_desk/office_desk_click_mouse.py)

原始模型／贴图／第三方字体不复制进本档案。获取方式见[环境与资产说明](../../../../../docs/variation/SETUP.md)，原许可见[资源说明](../../../../../tasks/assets/README.md)。不同家族的apple／plate等未确认共享，分别保留目录。[总索引](../../../README.md)。

## 2026-11-15候选静态分析

状态仍为待适配。本轮仅核对现有源文件、资产部件与材质／UV事实，实际SAPIEN绑定、并行隔离和A6仍未验证；见[候选分析](../../../../../docs/variation/OBJECT_CANDIDATES.md)。没有创建该对象的新方案、配置或运行代码。

## 历史：ClickMouse最小接入准备（当时未运行验收）

仅 `OfficeDeskClickMouse-Sharpa-v1` 已准备 original／ivory_matte／navy_satin 的最小材质入口、固定／随机示例及双环境短检脚本。默认关闭；Long 不变。档案状态仍为**待适配／运行未验收**，无新增 GPU 或 RGB 通过证据。

[接口、部件绑定和验证说明](../../../../../docs/variation/MOUSE_101408.md)；[唯一 catalog](../../../../../tasks/assets/variation/office_desk/mouse_101408/v1/catalog.json)；[短检脚本](../../../../../tools/variation/check_mouse_101408.py)。不复制一份参数源，不更改现有验收状态计数。

## 2026-11-16限定验收与交接

- 运行版本`78c9b2f212a50f4a9249acd30993dd9c6940d467`；固定证据版本`daaec9c9cd9c30da432dd23c65a720ed1cfb382e`。原生/关闭、三固定方案、指定集合随机复现与回合记录、修复后方案间物理属性/初态/按钮目标对照通过。
- 两轮只reset env1，env0状态、材质、记录、drive target以及base_camera／wrist_camera／human三路RGB保持不变；没有以全环境reset替代。
- 原任务GPU按钮目标时序修复与外观接入分开：CPU保留原_load_scene写入，GPU仅移至已有_after_reconfigure，沿用原joint/release值；不在每回合或局部reset新增全环境target写入。物理、机器人、几何及成功条件不改。
- **未验证**完整点击、Long、CPU后端运行、A6、大规模并行，以及修复前后内部warm-start轨迹等价；限定验收不是完整机器人成功。
- GPU历史累计35/600秒（86071失败10秒＋86453复测25秒）。历史失败与上轮墙钟71分54秒／超支26分54秒保留，不冲销。

[固定证据与真实任务图](https://github.com/DennisXu626/DexArena-Variation/blob/daaec9c9cd9c30da432dd23c65a720ed1cfb382e/docs/variation/MOUSE_101408.md)；[结构化结果](https://github.com/DennisXu626/DexArena-Variation/blob/daaec9c9cd9c30da432dd23c65a720ed1cfb382e/docs/variation/evidence/mouse_101408/retest_001.json)；[历史失败](https://github.com/DennisXu626/DexArena-Variation/blob/daaec9c9cd9c30da432dd23c65a720ed1cfb382e/docs/variation/evidence/mouse_101408/run_001.json)。完整证据入口沿用[任务说明](../../../../../docs/variation/MOUSE_101408.md)。请审验层复核文档增量后按仓库规范合并，并核对main实际落地；执行层不合并。
