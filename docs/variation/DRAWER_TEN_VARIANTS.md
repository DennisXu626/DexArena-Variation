# Drawer & Plug 十套家族外观

基线 `f0a09c9d1722abc831fd5c62ae77a42c9dece95c`。三个短任务已取得十套实景与固定方案证据。OpenDrawer／PickCharger 的随机和 A5 通过；InsertPlug 第二方向在 Charger 目标像素处停止，随机复现未运行。已有单对象验收记录继续适用其原版本。

## 家族编号与实际对象表

| 家族编号 | 抽屉 | 插座 | Charger |
|---|---|---|---|
| original | `original` · 原木顶／框／三层抽面及原内箱、把手 | `original` · 原银面与暗孔 | `original` · 原壳与双插脚 |
| variant_1 | `warm_white` · 暖白顶／框、浅橡木三层抽面、浅灰内箱、黑把手 | `warm_white` · 暖白哑光 PC | `ivory_matte` · 象牙白哑光 |
| variant_2 | `neutral_grey` · 石墨顶、中灰框、浅暖灰三层抽面、米白内箱、香槟把手 | `neutral_grey` · 炭黑哑光 PC | `navy_satin` · 海军蓝缎面 |
| variant_3 | `ash_greige` · 暖灰层压顶／框、白蜡木纹抽面、浅内箱、暖灰涂层把手 | `ash_greige` · 暖象牙细哑光 PC | `copper_metal` · 沿用铜色金属饰面 |
| variant_4 | `walnut_birch` · 深胡桃色耐磨台面／框、胡桃木纹抽面、浅桦木色内箱、深青铜把手 | `walnut_birch` · 卵石灰缎面 PC | `pebble_pc` · 暖卵石灰触感 PC |
| variant_5 | `mist_blue` · 深灰蓝覆面顶、雾蓝框与同系漆面、浅内箱、镍色把手 | `mist_blue` · 灰蓝斜光缎面 PC | `slate_shell` · 深板岩灰半哑塑料 |
| variant_6 | `olive_smoke` · 深橄榄哑光顶、橄榄框、烟色木纹抽面、浅内箱、铁灰把手 | `olive_smoke` · 橄榄灰细哑光 PC | `olive_polymer` · 偏暖橄榄聚合物 |
| variant_7 | `cream_copper` · 奶油缎面顶／框／抽面、浅内箱、铜色把手 | `cream_copper` · 杏奶色光滑缎面 PC | `sand_satin` · 暖沙缎面塑料 |
| variant_8 | `terracotta_oak` · 陶土色耐磨台面与框、橡木纹抽面、奶白内箱、深铁色把手 | `terracotta_oak` · 陶土棕细哑光 PC | `clay_pc` · 浅砖棕哑光 PC |
| variant_9 | `midnight_linen` · 深石墨覆面顶、午夜蓝框与抽面、亚麻灰内箱、淡金把手 | `midnight_linen` · 深蓝石墨缎面 PC | `graphite_fine` · 蓝相石墨细哑光 |
| variant_10 | `birch_plum` · 桦木色耐磨台面、暖中性色侧框、梅灰哑光抽面、浅内箱、古铜把手 | `birch_plum` · 淡梅灰细哑光 PC | `lilac_eggshell` · 灰紫蛋壳光塑料 |

[运行映射](../../tasks/assets/variation/drawer_plug/family_variants.json)是编号的唯一来源。材质参数来自各对象原 catalog。对象档案 [drawer](../../assets/appearance/objects/drawer_plug/drawer/README.md)、[socket](../../assets/appearance/objects/drawer_plug/socket/README.md)、[charger](../../assets/appearance/objects/drawer_plug/charger/README.md)。

## 绑定与证据范围

| 任务 | 实际加载的外观对象 | 取景与待确认内容 |
|---|---|---|
| OpenDrawer | 抽屉柜 | 原生闭合，台面、三层抽面与把手入镜 |
| PickCharger | 抽屉柜、Charger | 原生中屉 0.22 m，拍内壁、底板、壳体与插脚 |
| InsertPlug | 插座、Charger | 保留正式任务相机 RGB，局部板展示插座双孔、充电器壳与插脚 |

未列对象均为 N/A。抽屉继续使用 47 个现有网格文件到台面、边板、三层前板、内侧／背板／底板、把手、滑轨的语义分类。三层面板同一产品设计，滑轨和原几何不变；木饰面沿原 UV 纹向从原图提取明暗，覆面去掉木纹色。外框和内箱留有层次。插座 6 个壳体槽使用绝缘塑料表达，两个暗色内衬保持原样。程序 Charger 只在握持主体应用候选，原双金属插脚材质和组件原样保留。

## 实物与工艺参考

- [UMAGE Treasures](https://umage.com/collections/furniture/products/treasures-dresser?variant=50979061924174)提供连续木纹三层抽面和暖白侧围参考。胡桃、烟木和白蜡木色使用同一部件关系。多层哑面、色板、原生孔和浅压光把手的组合参照 [Turri Blues](https://turri.it/product/blues-chest-of-drawers/)；灰板和覆面工艺参照 [EGGER U708 ST9](https://www.egger.com/en/furniture-interior-design/decors/U708_9)。
- [Legrand Mallia Senses 哑面 PC 面板](https://www.legrand.ae/en/catalog/products/mallia-senses-socket-outlet-switched-1-gang-13-250-v-white-281111)和 [Legrand 聚碳酸酯技术表](https://assets.legrand.com/pim/NP-FT-GT/F01897EN-01.pdf)提供壳体哑面及深浅颜色参考，保留深色孔内衬。Charger 借鉴 [Apple 20W 电源适配器](https://www.apple.com/shop/product/mwvv3am/a/20w-usb-c-power-adapter)的绝缘壳与金属插脚对比，新色的细哑、缎面和蛋壳光是设计选择。
- 产品页用于工艺参考，参数是渲染设计值。未复制产品图、纹理、商标、模型或 UV；使用原资产与项目自制材质计算。具体映射和历史比较见 [抽屉／插座交付](DRAWER_SOCKET_APPEARANCE.md)及 [Charger 交付](CHARGER_A4_A5.md)。

## 构造与局部 reset

省略 `family_appearance` 或传 `enabled=False` 保持原生入口。原接口可以单独调用。家族开启时，旧外观配置不与家族配置叠加。原任务的抽屉开度遵循已有任务初始化。 `original` 恢复原参数与图像。

[逐环境固定选型](../../examples/variation/drawer_plug/family/family_ten_explicit.json)和[指定集合随机](../../examples/variation/drawer_plug/family/family_ten_random.json)可作为构造 kwargs。种子 `family_appearance.seed` 单独控制各环境选择，并随同一组 reset 次序复现。每个选中环境每回合只解析一次，后续阶段不再抽样。配置覆盖顺序为构造全局、构造 per_env、reset 全局、reset per_env。需要覆盖某个构造时的 per_env 方案时，也可使用 reset 的 per_env 字段。

```python
import json
from pathlib import Path

import gymnasium as gym
import torch
import tasks  # register the DexArena tasks

kwargs = json.loads(Path("examples/variation/drawer_plug/family/family_ten_explicit.json").read_text())
env = gym.make("DrawerPlugPickCharger-Sharpa-v1", num_envs=2, sim_backend="physx_cuda", **kwargs)
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
python -B tools/variation/check_drawer_ten_variants.py --static
python -B tools/variation/check_drawer_ten_variants.py --gallery PATH_TO_APPROVED_RUN_OUTPUT
```

任务短检经新授权后用同一脚本的 `--approval` 和 `--output`。原始 PNG、分割掩膜内的可见及变化像素、同坐标裁剪、选择记录、运行 manifest、首个失败和作业收据分开留存。拼图由真实原帧制成，每行至多三款。实际可见性、印刷方向、五金和内外分件需要人工审图。

[本轮任务实景与 A4／A5 结果](evidence/drawer_ten_variants/runtime_001/README.md)。草稿待 Dennis 审图。
