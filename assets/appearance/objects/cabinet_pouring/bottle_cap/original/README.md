# 原版：瓶盖

`original`不是第四张自制贴图。运行适配器在收集绑定时保存原生base_color／base_color_texture／roughness／metallic；选择original时逐项恢复保存值，不重新设计原图案。

外部视觉资源为`tasks/assets/task_object_meshes/cabinet_pour/bottle_4403/lid_vis/original-2.obj`及同目录MTL。原盖168个顶点、0个vt，MTL material_0_0无map_Kd；标记为任务既有视觉box，原红条不要求保留，但转动参照必须清楚。没有新的盖纹理或UV。

来源：[Hugging Face原资产仓库](https://huggingface.co/datasets/SIPAIR/DexArena/tree/b197a198fe50f41d70f563cfa7c88d3cc9f528b6/assets/task_object_meshes/cabinet_pour)、[任务代码](../../../../../../tasks/cabinet_pouring/cabinet_pouring_long.py)、[原始文件身份](asset_identity.json)。本档案仅引用原OBJ／MTL／原贴图，不复制第三方源资产；遵循原资源许可。HF与代码和运行库是三类独立版本，M1仅对8个指定文件作本地／运行资产一致性核对，不推断整包一致。详细获取方式见[SETUP](../../../../../../docs/variation/SETUP.md)。
