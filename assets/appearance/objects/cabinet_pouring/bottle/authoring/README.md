# 已发布标签的真实制作方法

脚本来自M2真实Pillow制作脚本；所有绘图操作、388×490 RGB画布、文字字号／坐标和三组配色保留。只将输出和字体路径参数化，并拒绝覆盖已有同名输出。瓶盖没有另一个纹理制作步骤：其方案参数取现有catalog，不新增UV／几何。

从仓库根用已安装的Pillow运行，字体路径替换为自己合法取得的Arial／Arial Bold文件：

```bash
python assets/appearance/objects/cabinet_pouring/bottle/authoring/make_assets.py --output appearance-authoring-output --font /path/to/Arial.ttf --bold-font /path/to/Arial-Bold.ttf
```

默认输出为当前目录appearance-authoring-output，**不指向运行素材目录**。生成catalog只是历史配套方案的制作产物，不是新loader或自动发布工具；发布仍须审查同步。不要把临时输出提交为第四套素材。

Arial字体文件不随仓库分发，使用者遵循字体许可。Pillow版本、字体具体字节、相关字体渲染库及PNG编码环境可能影响字节复现；历史Pillow版本没有单独记录，不猜测。本次本机CPU制作检查和真实匹配结果见[检查记录](check_result.json)。现有发布PNG来自历史文件，始终保留，不用本次重生成结果替换。

图案为项目自行程序绘制，无外部插画；原模型／原标签仍按其第三方来源获取，新增图案不改变原资源许可。历史脚本身份及最小改动见[provenance.json](provenance.json)。
