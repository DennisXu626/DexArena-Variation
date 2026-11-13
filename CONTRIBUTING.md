# 团队贡献规范

main是经检查供大家使用的集成版本。每项工作从最新main开一个任务分支，通过Pull Request（PR，向维护者请求审查和合并一组提交）合入；不在main开发、不随手直接推main，不要求每人长期维护个人分叉。

## 一次标准提交

所有命令从仓库根目录执行，工作区先保持干净；有未提交改动先处理，不用强制覆盖：

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/bottle-appearance
# 编辑本任务相关文件后：
git status --short
git diff --check
git diff
python tools/variation/check_static.py
git add -- tasks/assets/variation/cabinet_pouring/v1/catalog.json
git diff --cached
git commit -m "说明本次外观改动"
git push -u origin feat/bottle-appearance
```

然后在仓库GitHub页面选择 **Compare & pull request**，base选择main，按模板写目标、改动、实际验证、截图／证据及剩余问题。分支名按任务选，如 `feat/pose-regions`、`fix/reset-isolation`，不要多人共用一个任务分支。不要对assets／outputs随手 `git add .`，逐一添加明确文件。

## 审阅和合并

- 由Dennis或指定负责人审阅后合并；至少一位有效审阅者批准，解决所有未关闭讨论。改代码后旧批准应失效，重新请求审阅。作者不能批准自己的PR。
- 公共任务接口、配置契约和仓库规范的CODEOWNERS（文件审核责任人）为 `@DennisXu626`。规则被服务器支持并启用时必须有code-owner审阅；文件本身不会自动启用保护。
- Dennis自己后续改动也由另一位具备权限的成员审阅；若该改动还需要CODEOWNER批准，先由维护者确定另一个符合资格的责任人，不依赖自审或管理员绕过。本轮尚未邀请任何成员。
- 先解决冲突并验证受影响部分，使用squash合并（把本PR整理为main上的一条提交），合并后自动删除任务分支。不强推、不删除main。
- main的**实际强制保护状态**见仓库Settings的Branches／Rules页面及建仓验收记录；若套餐限制不支持，仍执行本规范，但不能称它已被服务器强制执行。Dennis应在邀请成员前解决这一差距，不通过把仓库公开来规避。

GitHub依据：[作者不能批准自己的PR](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/approving-a-pull-request-with-required-reviews)、[CODEOWNERS与保护](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)。

## 分工与修改边界

- 外观同学维护方案／小素材及实际部件绑定；提交同视角原版／改版实景、盖子角度参照、阶段一致性和物理不变证据。标签和原红条可替换，盖子必须保留清楚的非对称转动参照。
- 位姿同学维护原区域请求／坐标／记录；先检查最终有效表示、合法和越界处理、局部reset隔离。PickBottle柜内起点不能被UnscrewCap桌面请求覆盖；区域扩展先讨论。
- 集成负责人协调 `cabinet_pouring_long.py`、两个子任务以及 `variation.py` 共用入口。`variation.py` 同时包含外观和位姿，不按“各自一份文件”重复实现；开始前约定本次修改段落和接入顺序，避免两套不兼容接口。
- 只改讨论范围内内容，不随手优化／重构。新增功能、范围扩大、仿真核心、机器人、几何、碰撞、物理参数或成功条件变更先讨论。

## 最小验证和交付

执行最小实现、最小修复、最小测试。先跑静态检查，外观改动再在获授权环境检查真实效果与物理不变；位姿改动检查合法性、最终记录和局部reset；共用reset／渲染修改覆盖受影响的并行路径。文案修改不要求完整GPU验证，不以测试数或进程正常退出替代能力证据。

每次交付同步配置示例、用法、已知限制；把成功、未完成、未验证分开写，工程触发不写成机器人成功。运行和实验先取得具体资源授权，代码推送本身不授权GPU、训练或下载大型数据。

不提交对象包、数据集、录像、缓存、模型权重、凭据、虚拟环境和个人机器配置；不共享HF／GitHub token。Git只新增代码、配置、小型自制素材和精简文档。上游已有受版本管理资源与LICENSE／NOTICE保留，第三方数据按原授权渠道获取。

本次建仓在本地 `bootstrap/team-repo` 分支检查后，允许一次性首次发布main。发布后立即尝试并核对保护设置；这不是后续绕过PR的理由。本轮不启用Actions、CI、网站、训练工作流或自托管runner。
