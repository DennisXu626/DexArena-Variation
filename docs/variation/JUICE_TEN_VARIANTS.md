# Juice Preparation 十套方案

本轮从团队 main `58de243` 建分支 `codex/juice-preparation-ten-variants`，快进接入 PR19 `b611faf`。保留 original 和原有 variant_1/2，增加 variant_3 至 variant_10。唯一参数源为 `tasks/assets/variation/juice_preparation/v1/catalog.json`，版本 juice-ten-v3-preview。没有新增模型、UV 或第三方贴图文件。

|ID|冰箱|苹果|底座|盖子|
|---|---|---|---|---|
|1|鼠尾草绿|金黄|深绿|浅绿灰|
|2|陶土红|青绿|灰蓝|浅米灰|
|3|奶油白|葡萄紫|酒红|暖灰白|
|4|冰蓝|青蓝|钴蓝|浅蓝灰|
|5|柠檬黄|鲜橘橙|柠檬黄|浅灰|
|6|浅薰衣草紫|宝石蓝|深紫|淡紫灰|
|7|杏橙|珍珠白|鲜橙|浅杏色|
|8|薄荷青|玫红|深青|暖白|
|9|灰玫瑰粉|炭黑|可可棕|浅玫瑰灰|
|10|银灰|荧光黄绿|象牙白|冷灰|

配色为目标色，最终像素继承原材质与纹理明暗。冰箱仅修改原外壳目标槽，苹果保留果梗与纹理，底座不修改透明杯体、按钮、旋钮或刀片；独立盖及集成盖沿用同一 lid 配方。前两套参数与 PR19 相同。

六个入口继续使用 `juice_appearance={"scheme_id":"variant_3"}`，也支持原有 per_env 固定选择。随机选择未实现，本轮不新增此接口。

## 验证方法

使用独立 Juice 检查器，借鉴 PR31 最终配对审核方法，保留共享检查器不变：

- `check_juice_ten_paired.py <入口后缀> --output <新目录>`：每入口 original＋十套 A4，以及十套双向 A5。核对实际绑定、纹理、物理签名、原版恢复、未选行状态/活动控制目标/记录/任务 RNG/多相机 RGB。原生和候选保持相同 reset 与 readback 历史。
- `check_juice_short_trace_paired.py --stage <入口后缀> --output <新目录>`：每入口每 ID 分别用全新 Python worker 串行运行原生与候选实例；各实例仍为 2env。先检查物理和控制初态，再比较四步相同动作。
- `check_juice_critical_reset.py --output <新目录>`：PressButton 与 Long 按钮末步前计数 3、Long 阶段 4，以及苹果运动缓存/路线锁存受控状态的双向局部 reset 隔离。不是机器人完成轨迹。
- `render_juice_preview.py`：CPU 物理＋GPU 渲染真实任务预览，六类视角，十一方案三列图册；杯内苹果为明确标注的受控放置。

数值阈值 1e-6；RGB 最大差 1、最多 8 通道，不继承 Meal 特定相机例外。目标不可见时保留零可见像素记录，不据此宣称果皮实景已审查。正式 A4/A5 使用 Sharpa、2env、PhysX CUDA＋GPU 渲染、seed7、noise0。

限定运行结果见 [本轮证据](evidence/juice_ten/README.md)：66 行 A4、120 例 A5、66 对短步与 6 例临界检查通过。初轮 CloseFridge 短步失败及独立进程补跑通过均保留。历史 PR19 证据保持原范围，不冒称十套实测。完整策略成功率、其它手型/并行规模/噪声、长期压力及性能显存未验证。

短步检查器失败定位及最终全量复验见 [根因记录](evidence/juice_ten/root_cause/README.md)，不再依赖同一进程 close/GC 提供物理后端隔离。

## 新配色最终回归

本版修正原图冷灰果皮遮罩，并为3～10号苹果加入目标饱和度/亮度映射；1/2号旧输出保留。作业138333已重新完成全六入口66行A4、120例A5、66对四步与6例临界检查，轨迹最大差0。以[新版证据](evidence/juice_ten/v3_regression/README.md)为当前配色的验收来源，旧版证据只保留其历史范围。本轮作为十方案分支的后续提交交付，PR由作者发起。
