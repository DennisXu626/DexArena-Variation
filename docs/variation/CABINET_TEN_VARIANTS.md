# Cabinet & Pouring 十套家族外观

Dennis 于 2026-11-22 批准四个短任务中的十套对象外观（`variant_1` 至 `variant_10`），原版单列。实景覆盖开闭柜、瓶签、附着盖标记和碗。16 颗液滴在独立场景中逐颗判色。阶段切换的渲染问题见下文。

## 家族编号与实际对象表

| 家族编号 | 柜子 | 瓶身／盖 | 碗／模拟液滴 |
|---|---|---|---|
| original | `original` · 原模型门、柜身、内板、把手 | `original` · 原瓶及原盖 | `original` · 原碗和液滴 |
| variant_1 | `oak_warm_white` · 浅橡木门、暖白板、浅灰内衬、黑把手 | `ocean` · 沿用已验收海蓝瓶／盖 | `ocean` · 沿用海蓝器皿和液滴 |
| variant_2 | `sage_walnut` · 灰绿漆门、深胡桃身、浅灰内衬、古铜把手 | `citrus` · 沿用已验收柑橘瓶／盖 | `citrus` · 沿用柑橘器皿和液滴 |
| variant_3 | `smoked_linen` · 烟熏木门、同系深木外壳、亚麻色内衬、暖古铜把手 | `violet` · 沿用已验收紫色瓶／盖 | `violet` · 沿用紫色器皿和液滴 |
| variant_4 | `birch_dust_blue` · 雾蓝层压门、浅桦木色直纹柜身、灰白内衬、镍色把手 | `spring_water` · 清泉面标、青白盖配深蓝标线 | `spring_water` · 暖白釉碗、浅青水色 |
| variant_5 | `cream_nickel` · 奶油亮缎门、浅木柜身、暖褐灰内衬、镍色把手 | `black_tea` · 红茶面标、深栗盖配金棕标线 | `black_tea` · 灰绿青釉、琥珀茶色 |
| variant_6 | `walnut_ivory` · 胡桃木门、象牙覆面、米灰内衬、深古铜把手 | `peach_juice` · 蜜桃面标、莓红盖配奶白标线 | `peach_juice` · 炭色炻器、蜜桃橙液滴 |
| variant_7 | `slate_ash` · 板岩灰覆面门、灰白蜡木色柜身、暖白内衬、淡香槟把手 | `mineral_silver` · 矿泉面标、缎银瓶身、深灰盖配浅标线 | `mineral_silver` · 灰蓝亮釉、近透明的淡青色液滴 |
| variant_8 | `brick_putty` · 陶土色涂装门、泥灰覆面、浅沙内衬、深褐五金 | `green_tea` · 绿茶面标、黄绿盖配深绿标线 | `green_tea` · 沙黄釉、淡橄榄茶色 |
| variant_9 | `reed_birch` · 草甸灰绿覆面门、中棕木身、浅沙内衬、深灰金属把手 | `berry_soda` · 莓果面标、墨紫盖配橙标线 | `berry_soda` · 雾粉釉、莓果红液滴 |
| variant_10 | `ink_maple` · 墨蓝缎漆门、枫木色浅木身、暖灰内衬、黄铜色把手 | `coffee_milk` · 咖啡奶面标、焦糖盖配深咖标线 | `coffee_milk` · 深紫灰炻器、奶咖色液滴 |

[运行映射](../../tasks/assets/variation/cabinet_pouring/family_variants.json)是编号的唯一来源。材质参数来自各对象原 catalog。对象档案 [cabinet](../../assets/appearance/objects/cabinet_pouring/cabinet/README.md)、[bottle](../../assets/appearance/objects/cabinet_pouring/bottle/README.md)、[bottle_cap](../../assets/appearance/objects/cabinet_pouring/bottle_cap/README.md)、[bowl](../../assets/appearance/objects/cabinet_pouring/bowl/README.md)、[beads](../../assets/appearance/objects/cabinet_pouring/beads/README.md)。

## 绑定与证据范围

| 任务 | 实际加载的外观对象 | 取景与阶段 |
|---|---|---|
| OpenCabinet | 柜子 | 原生关门，机位纳入门、把手和顶板 |
| PickBottle | 柜子、动态瓶身、附着盖、16 颗液滴 | 原生开门 90°，柜内层板、开门内壁和瓶子 |
| UnscrewCap | 瓶身、盖、液滴 | 按任务已有动态、固定、开口瓶和附着／固定／自由盖登记实际材质；桌面近景检查旋转标记 |
| PourBeads | 原生开口瓶、碗、液滴 | 正式任务桌面碗和瓶；附加实例只工程挪动液滴以免遮挡，粒径 4 mm，数量 16 |

未列对象在对应任务中为 N/A。柜体沿用 PR #20 语义材质槽，门长边用原方向，顶板、侧板和可见板边沿已审映射，内侧壁／背板／底板／层板和把手独立。瓶和盖复用现有 UV 与非对称标记零件，从活动表示到停放表示都用本回合编号。碗实际是一张原漫反射槽，新的釉色保留可见明暗，不把原 UV 当作可区分口沿、内壁、外壁的槽。液滴沿用原球形、原数量和 PhysX 状态，颜色是有可读性的液体外观近似。

## 实物与工艺参考

- [IKEA ENHET 单门搁板柜](https://www.ikea.com/ae/en/p/enhet-wall-cb-w-1-shlf-door-white-oak-effect-s69321013/)作为独立柜门和框体饰面参考。原色浅木、深胡桃、灰白木的板件尺度和内外分别处理，参照 [IKEA EKET 胡桃木饰面单门柜](https://www.ikea.com/us/en/p/eket-wall-cabinet-1-door-brown-walnut-effect-s09581179/)。新方案选择哑光层压、缎面漆及原模型用色，封边搭配借鉴 [Formica 封边与层压饰面对照](https://www.formica.com/-/media/project/formica/north-america/document-library/data-sheets/edgeband-and-3d-laminate-cross-reference-guide.pdf?rev=6037ca87af8e4304a858babaae2a7b12)。
- [ITO EN 瓶装绿茶](https://itoen.com/products/unsweetened-green-tea)提供聚合物盖、对比清楚的纸标色块和浅茶色液体参考。水、茶、果汁、汽水和奶咖各用项目自制名称及插图，图案与商标不取自产品。活动标签布局适配现有 388×490 UV，非对称标记沿用盖上已有零件。
- [KINTO Ceramic Lab](https://kinto-usa.com/collections/ceramic-lab)提供釉面与炻器参考。偏白灰蓝的釉面较光滑，深炻器和暗纹较哑，接触材质参数保持；液滴仍是正式任务的球体代理。
- 数字材质用于渲染，不援引厂商测量的 BRDF。未复制参考图、商标、第三方模型或原纹理。新增柜身木纹在现有 UV 上复用 PR #20 自制方法，标签是仓库自制 PNG，釉面和液滴由参数生成。来源遵循 [仓库许可](../../LICENSE) 和 [原资产说明](../../tasks/assets/README.md)。

## 构造与局部 reset

省略 `family_appearance` 或传 `enabled=False` 保持原生入口。原接口可以单独调用。家族开启时，旧外观配置不与家族配置叠加。既有 variation.initial_pose 可以同时使用。 `original` 恢复原参数与图像。

[逐环境固定选型](../../examples/variation/cabinet_pouring/family/family_ten_explicit.json)和[指定集合随机](../../examples/variation/cabinet_pouring/family/family_ten_random.json)可作为构造 kwargs。种子 `family_appearance.seed` 单独控制各环境选择，并随同一组 reset 次序复现。每个选中环境每回合只解析一次，后续阶段不再抽样。配置覆盖顺序为构造全局、构造 per_env、reset 全局、reset per_env。需要覆盖某个构造时的 per_env 方案时，也可使用 reset 的 per_env 字段。

```python
import json
from pathlib import Path

import gymnasium as gym
import torch
import tasks  # register the DexArena tasks

kwargs = json.loads(Path("examples/variation/cabinet_pouring/family/family_ten_explicit.json").read_text())
env = gym.make("CabinetPouringPickBottle-Sharpa-v1", num_envs=2, sim_backend="physx_cuda", **kwargs)
env.reset(seed=7)
env.reset(options={
    "env_idx": torch.tensor([1], device=env.unwrapped.device),
    "family_appearance": {"mode": "explicit", "scheme_id": "original"},
})
print(env.unwrapped.family_appearance_records[-1])
env.close()
```

记录包含环境索引、回合索引、家族编号、catalog 版本和实际加载对象的方案 ID。Long 继续有旧接口的单环境阶段边界。家族选型现覆盖上表短任务，传给 Long 会明确拒绝；新版 Long、完整机器人任务、A6 和训练没有运行验收。

## 证据入口

```text
python -B tools/variation/check_cabinet_ten_variants.py --static
python -B tools/variation/check_cabinet_ten_variants.py --gallery PATH_TO_APPROVED_RUN_OUTPUT
```

任务短检经新授权后用同一脚本的 `--approval` 和 `--output`。原始 PNG、分割掩膜内的可见及变化像素、同坐标裁剪、选择记录、运行 manifest、首个失败和作业收据分开留存。拼图由真实原帧制成，每行至多三款。实际可见性、印刷方向、五金和内外分件需要人工审图。

作业 128861 验证柜体开闭，128933 补齐 PickBottle 瓶签，128943 验证 UnscrewCap 附着盖十款、逐款恢复与双向局部 reset。129056 补齐 UnscrewCap 随机复现，以及 PourBeads 的绑定、初态、恢复、随机复现、双向局部 reset 和瓶外液滴逐球检查。[柜体](evidence/cabinet_ten_variants/runtime_001/README.md) · [瓶签](evidence/cabinet_ten_variants/runtime_003/README.md) · [附着盖](evidence/cabinet_ten_variants/runtime_004/README.md) · [倾倒与液滴](evidence/cabinet_ten_variants/runtime_006/README.md)

**已知问题：UnscrewCap 阶段切换时的画面跳变。** 作业 129056 在自由盖首帧拍到前景遮住瓶与盖。129064 的补充机位中两者保持可见，但默认基座相机在关闭外观和 `variant_9` 两组中，均把 442 个像素标为记录在桌下的瓶子放置标记。正式机位在切盖前就看不到瓶和盖，无法判断它们是否在切换后消失。根因仍待定位。Dennis 已将此问题留待会议反馈，本次批准范围为物体外观。[首次差异](evidence/cabinet_ten_variants/runtime_006/cap_first_difference.json) · [原生与第 9 套对照](evidence/cabinet_ten_variants/runtime_009/RESULTS.md)

作业 129146 用 `variant_9` 重渲染演示回合 0 的全部 196 个记录状态（20 帧/秒，共 9.8 秒）。回放保留了约 8.75 秒处的画面跳变。该录像属于记录状态回放，完整机器人任务成功率、Long 和 A6 仍未验证。
