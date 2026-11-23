# Package Opening 十套外观候选

用户已审核十套实景；三入口A4/A5、随机复现及全部33对同动作短步通过。完整机器人成功率未测；未commit／push。

分支codex/package-opening-expand-to-10；catalog版本package-opening-preview-v3。前两套对象参数及方案映射保持原样；新增variant_3～10。第八套按用户修订使用深海蓝／冰蓝。

[唯一catalog](../../tasks/assets/variation/package_opening/v1/catalog.json) · [运行证据](evidence/package_opening/ten/README.md)

|ID|盒身 / 翻盖|苹果|接收盘|
|---|---|---|---|
|variant_1|#AB7950 / #D5B186|#D7AC42|#245C59|
|variant_2|#415A6B / #829FB0|#8EA25C|#EFE0BC|
|variant_3|#637D68 / #B8C9AE|#C83D42|#E7B19A|
|variant_4|#79678F / #C5B7D5|#DC8735|#414A53|
|variant_5|#3E454D / #AEB7BF|#D97DA0|#985468|
|variant_6|#B96350 / #E7AC92|#B8C96B|#653D70|
|variant_7|#BA943B / #E6D28E|#8252A1|#414F8D|
|variant_8|#244C73 / #B8D8EA|#E8E1CF|#A4D0C9|
|variant_9|#AF9270 / #E0CFB0|#453345|#C58C3E|
|variant_10|#783C50 / #C699A7|#47AEB8|#8ABDDD|

盒身、翻盖、内底与提拉片分别配色；保留原粉色底部色带。盘面盘底沿用原共用材质槽。苹果保留原UV与纹理细节；新增八套启用include_yellow_skin和match_target_value以覆盖浅黄果皮并呈现白色／深色的目标明暗。原golden／green未启用新亮度映射，CPU随机合成像素对照与HEAD旧函数输出逐像素一致。

新预览入口tools/variation/render_package_ten.py通过正式package_appearance绑定整套方案，五视图均为任务原生reset状态；按original、variant_1～10的ID标图。无新增UV、几何或外部图片。旧预览脚本同步接受新增可选亮度参数。

GPU并行审查前仍需将现有检查器从固定两套扩展到十套，覆盖新贴图亮度路径的逐槽身份、恢复原版及双向局部reset；现有历史87021不能作为新增八套的验证。

## 正式环境短检更新

三入口A4共33行、双向A5共60例及随机序列复现全部通过。另加同动作4步回归：开包装、取苹果11行通过，Long在variant_1超过数值阈值，其余9套未测，不能标整体环境验收通过。详见[正式环境结果](evidence/package_opening/environment_validation/README.md)。

## 最新：同历史全量复验通过

本家族全部入口original＋十套A4、双向A5及随机复现均通过；Package另完成33对串行短步。结果、实际运行身份、原帧和范围见[全量复验报告](evidence/package_opening/paired_revalidation/README.md)。旧失败不删除，完整机器人成功率仍未测。

## PR31-R1 控制目标覆盖修复与 G3 复验（2026-11-23）

修复提交 `425a54a` 直接采集手臂阻抗及 articulation 驱动目标，补上 A5 未选控制目标比较。Server 3 G3 作业135140三入口33行A4、60例A5及随机复现通过，控制目标未选前后及选中相对native最大差均为0。作业135189追加五视图对象近景。48格原生相机原帧、实际ID、完整签名、收据与视角遮挡限制见[本次报告](evidence/package_opening/pr31_r1_g3/README.md)。本次是修复分支作者复验，尚待审验层查收；完整机器人成功率未测。
