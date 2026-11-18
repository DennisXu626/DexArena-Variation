# Nut & Bolt / nut

free Actor与threaded_nut link共用方案；既有segment 0提供候选参照色，其余五段为body。

- [唯一材质catalog](variants/v1/catalog.json)：original与两候选，无新增UV或贴图。
- [绑定与保护规则](bindings.json)：原资产身份、实际表示和角色对应。
- [正式接口与验收](../../../../../docs/variation/NUT_BOLT_APPEARANCE.md)：默认关闭，三短任务范围。

original恢复本次实际加载材质。三个短任务的正式接入已实现。当前输入的CPU契约检查通过，正式CPU／标准CUDA隔离与真实任务图按新版本重新验收；历史色样或stub不作为运行证据。
