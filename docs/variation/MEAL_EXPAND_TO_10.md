# Meal Preparation 十套外观（当前v3）

用户已审核v3实景；四入口original＋十套A4、双向A5和随机复现全量通过。完整机器人成功率未测；未commit／push。

[运行证据与限制](evidence/meal_preparation/ten_final/README.md) · [参数审阅板](figures/meal_expand_to_10.html) · [唯一运行catalog](../../tasks/assets/variation/meal_preparation/v1/catalog.json)

分支codex/meal-preparation-expand-to-10，基线aee41a3。original加十套新外观；只改外观配方，不改任务、几何、碰撞和物理。用户明确同意贝果variant_1～10重新排列，因此不再声明原两套全部不变。

|方案|盒身 / 盖|盘面|勺体 / 握套|番茄|贝果|
|---|---|---|---|---|---|
|variant_1|#57768A / #9AB7C6|#274A88|#CBD0D6 / #294875|#EDAE36|极浅烘|
|variant_2|#A84C3C / #C48679|#FFFFFF|#56606B / #D38A5C|#88284C|浅烘|
|variant_3|#536B50 / #A8BA91|#E8DAB6|#C6C9BD / #667C54|#D87532|轻金黄|
|variant_4|#233F54 / #527B8B|#E2A18D|#B8C7CE / #CE765D|#9CCB45|金黄|
|variant_5|#B18B31 / #DDC47C|#343C43|#777C80 / #D3AA43|#36B8BD|中烘|
|variant_6|#76658C / #B7A5C6|#DDD2E4|#CBC2D2 / #58415F|#4268D0|中深烘|
|variant_7|#722F43 / #B16C7A|#B8BEC0|#BDB8B1 / #75384E|#8650C4|深烘|
|variant_8|#478D87 / #A3CCC1|#254C42|#B3BDB7 / #D4B681|#E788B1|重深烘|
|variant_9|#B59A77 / #E0CFAB|#C68A32|#B87333 / #E7DCC5|#E9E3D5|轻微烤焦|
|variant_10|#D5D9DA / #F1F0E9|#6C7883|#4E5963 / #9C6248|#41454C|明显烤焦|

无新增UV、几何、配料或第三方图片。贝果基于授权原纹理，使用逐级增加gamma、逐级降低RGB gain与bias的配方保留表皮细节和暖色。旧light／dark配方保留便于历史复现，当前catalog不再引用。

初轮v2记录见[123801](evidence/meal_preparation/ten/README.md)；本轮中间123814与最终123816分别留档。旧证据不替代当前源码的结果。现有两份旧检查脚本固定前两套，十套完整遍历使用tools/variation/check_meal_ten.py。

本轮静态检查和差异格式检查通过；完整归档检查受既有Cabinet CRLF哈希差异影响，未修改该家族。

## 正式环境短检更新

按用户提供的十套验证规范执行后，A4四入口44行均通过，A5只有PlaceBread完整通过，另三入口有严格RGB判据失败。完整结论、未测项及原始证据见[正式A4/A5记录](evidence/meal_preparation/environment_validation/README.md)。前文限定验证结果不能替代本次结论。

## 用户确认重评

ScoopTomato A5按已确认新RGB判据离线重评20/20通过，原始失败JSON保留；随机复现未测。Meal剩余A5问题为开盒和长任务的恢复像素差，最小定位另行记录。

## 最新：同历史全量复验通过

本家族全部入口original＋十套A4、双向A5及随机复现均通过；Package另完成33对串行短步。结果、实际运行身份、原帧和范围见[全量复验报告](evidence/meal_preparation/paired_revalidation/README.md)。旧失败不删除，完整机器人成功率仍未测。
