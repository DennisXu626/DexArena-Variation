# Cabinet & Pouring 定向补测准备

[实际运行结果和实景证据](runtime_003/README.md)。下文保留两阶段准备时的设计和停止条件。

复用 [作业 128861](runtime_001/README.md) 的开闭柜十套、既有材质及初态、逐款恢复、随机复现、双向 A5，以及 UnscrewCap 的显式 original 等价证据。旧报告保留原判定。新阶段只补瓶签、瓶盖标记、碗和瓶外液滴。

## 单款探针

- 源资产的 original-3.obj 将瓶签面分配给 material_2_0，MTL 引用 texture_1.jpg。原图为 194×245，variant_9 对应 berry_soda.png，388×490，宽高比一致。旧小窗仅证明新印刷当时不可辨。
- 对正式 PickBottle 先取固定机位的 original 图。机位从原生 seed 7 的瓶身位姿确定，保留旧 base 和腕部相机，以独立展示机位看印刷区。两个预列机位择一，随后固定。屏幕近景须含真实实体 ID，按实际网格、缩放与 UV 复投影标签面。native 模板用于校准 UV 方向，候选模板来自对应 catalog 的真实 PNG。
- 热切换时保持原生 pose、segmentation、相机、光照和曝光。逐项记录实际可见瓶身表示、网格、槽内像素与预期文件。只有实际帧的印刷分布匹配预期，才判定可见；以模板对照和人工审图确认。已有画面只变底色不足以通过。
- 若热切换未呈现新图，再做候选先绑定及私有纹理原位上传两个对照。实验纹理在首帧前按环境和表示独立分配，只写私有像素，保持生产文件不变。只有热切换仍像旧图、私有上传能看到预期图案，才准备接入生产瓶签槽。原版保留原像素、尺寸、采样与 sRGB；候选转成槽位需要的格式及尺寸，保留原 UV。无法得到有区分力的实景时停止，交回记录和原帧。

## 定向补测

| 项目 | 检查与交付 |
|---|---|
| PickBottle | 同一补充机位取 original＋十款的实际标签。若改绑定，只补受影响的瓶身表示、恢复及局部 reset 隔离，复用旧柜体证据。 |
| UnscrewCap | 先在桌面原版验证瓶身、盖与非对称标记在补充机位可见，且同帧实体掩膜有效。再拍十款对应印刷及标记，查恢复、随机复现和双向局部 reset。原生固定、工程触发自由盖和开口瓶各保留画面，单列工程触发。 |
| PourBeads | 碗在桌面原位。复用 PR #21 的碗位视角，实体分割内分别取碗面和轮廓内带，并实际检查口沿。核对瓶身、碗和全部 16 颗球的材质绑定、原版恢复、同 seed 初态、随机复现和双向局部 reset。 |
| 独立液滴 | 另建 PourBeads，按 PR #21 把原来的 16 颗、半径 4 mm 的球移至瓶外固定 4×4 点阵。通过同帧实体 ID 逐球统计颜色、可见像素和变化。正式实例保留瓶内原生初态。 |

普通补测不修改 task pose。阶段转换与独立液滴位移只在检查器中工程触发。首个关键失败即保存已有证据并停止。Long、训练、机器人全程任务均在此次范围外。

## 运行入口

```text
python -B tools/variation/check_cabinet_ten_variants.py --static
python -B tools/variation/check_cabinet_ten_variants.py --followup label-probe --approval APPROVED.json --output NEW_RUN_DIR
python -B tools/variation/check_cabinet_ten_variants.py --followup targeted --approval APPROVED.json --output NEW_RUN_DIR
python -B tools/variation/check_cabinet_ten_variants.py --gallery NEW_RUN_DIR
```

探针范围为 cabinet_label_probe，定向阶段为 cabinet_pouring_followup。两条 GPU 入口要求授权、冻结提交、CPU 预检和独占单卡作业。定向阶段还需上一步可见印刷通过的作业、manifest 哈希及核对后的绑定路径。CPU 合成对照可验证算法拒绝错印刷，无法代替 SAPIEN 实景。当前两阶段均待 Dennis 新授权。
