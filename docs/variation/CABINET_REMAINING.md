# Cabinet 剩余对象：外观修复及限定运行通过

cabinet、bowl、beads已完成original＋Ocean/Citrus最小接入。作业88777在源码`a18cd0e26708fe2f39ff12a8a84c28735571039a`上完成真实渲染与全矩阵短检，leader已人工核对九张原版/候选图。**待Dennis最终查收，PR #10未合并，验收统计暂不增加**。详见[实景、测量和收据](evidence/cabinet_remaining/leader_fix_005/README.md)。

## 方案与任务

唯一参数源为[cabinet-appearance-v1.2 catalog](../../tasks/assets/variation/cabinet_pouring/v1/catalog.json)。同一方案控制瓶/盖和实际加载对象，不新增逐对象任意混配。

| 方案 | 柜体 | 碗 | 珠子 | 瓶/盖 |
|---|---|---|---|---|
| original | 原纹理像素与材质参数 | 原纹理像素与材质参数 | 原蓝色 | 原行为 |
| ocean | 蓝绿木面，保留纹理细节 | 暖色浅调派生纹理 | 橙色 | 原Ocean |
| citrus | 暖木调，保留纹理细节 | 深绿调派生纹理 | 紫色 | 原Citrus |
| violet | 原版 | 原版 | 原版 | 原Violet |

| 正式Sharpa入口 | cabinet | bowl | beads | 验证范围 |
|---|---|---|---|---|
| CabinetPouringOpenCabinet-Sharpa-v1 | 通过 | 不适用 | 不适用 | 2env |
| CabinetPouringPickBottle-Sharpa-v1 | 通过 | 不适用 | 通过 | 2env |
| CabinetPouringUnscrewCap-Sharpa-v1 | 不适用 | 不适用 | 通过 | 2env |
| CabinetPouringPourBeads-Sharpa-v1 | 不适用 | 通过 | 通过 | 2env |
| CabinetPouringLong-Sharpa-v1 | 通过 | 通过 | 通过 | 1env，工程检查 |

各对象的实际部件、材质槽及源文件身份见[柜体](../../assets/appearance/objects/cabinet_pouring/cabinet/bindings.json)、[碗](../../assets/appearance/objects/cabinet_pouring/bowl/bindings.json)、[珠子](../../assets/appearance/objects/cabinet_pouring/beads/bindings.json)。

## 实现与使用

沿用[固定/双环境示例](../../examples/variation/cabinet_pouring/appearance.json)和[随机示例](../../examples/variation/cabinet_pouring/appearance_random.json)，通过`variation.appearance`选择固定、per_env或集合随机；每回合选择固定，各表示复用同一选择。外观默认关闭。**initial_pose仍仅允许PickBottle/UnscrewCap**；其范围和采样不扩展。

柜体/碗在首次批量渲染前绑定环境私有纹理，reset仅上传对应原版或派生像素，保持纹理对象稳定，避免运行中替换引用后画面未刷新。原生贴图不被写入；original和新对象的violet恢复原像素及参数。柜门把手`original-36.obj`、透明部件及其它非着色细节保留原版。未修改UV、几何、碰撞、机器人、成功条件或第三方渲染库。

碗内外/边缘沿用原单材质，未新增独立材质槽。珠子是模拟倒出内容物的原生球，默认16颗、半径4mm；启用外观时分env使用同一个原生球构建helper后合并，数量/物理/初态关系不变。独立珠子近景仅供诊断，不是正式任务初态图。

[派生纹理脚本](../../tools/variation/make_cabinet_tints.py)与[来源/hash记录](../../tasks/assets/variation/cabinet_pouring/v1/object_tints/provenance.json)随仓库保存；12张派生图引用原纹理亮度和新配色，许可仍跟随PartNet/RoboCasa原资源，不能视为完全原创素材。原模型/原纹理按[原资产说明](../../tasks/assets/README.md)获取；无新字体或外部图片。

## 已验证及边界

四短任务各2env：实际绑定/像素、原版恢复、物理/初态、随机复现/记录、两轮env1局部reset通过，env0四路RGB像素差均0。新实例对照和同实例切换的柜体/碗ROI最大通道差均0。独立珠子蓝/橙/紫与局部隔离通过；原瓶/盖工程阶段和既有xy_v2合法点必要回归通过。Long仅1env原生表示工程检查。

未验证完整机器人任务、训练、A6、Long双环境、其它手型或长时间压力；没有用户物理步不代表框架内部无warm-start。

CPU静态复核命令：

```bash
python -B tools/variation/check_static.py
python -B tools/variation/check_appearance_archive.py
python -B tools/variation/check_cabinet_remaining.py --static
git diff --check
```

GPU脚本仍需独立批准、容量/停止保护、固定源码身份和提交时限；本页不是下一轮运行授权。本轮5次作业累计260/300分配秒，停止后不自动沿用余额。

历史证据：[初次视觉未达标](evidence/cabinet_remaining/README.md)、[旧探针失败](evidence/cabinet_remaining/visual_fix_001/README.md)。历史时点和预算不覆盖本次结果，也不被删除。
