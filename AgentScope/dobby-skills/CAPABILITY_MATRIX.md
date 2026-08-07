# Dobby 初始化能力清单

| 能力 | 负责人 | 边界 |
| --- | --- | --- |
| 附件传输与解析 | 平台固定工具 | 每个上传附件在进入模型前解析；MinerU 优先，本地解析降级；不限制文件数量 |
| 执行计划 | 初始化主智能体 | 模型收到消息后第一项业务动作是 `TaskCreate`，并持续更新真实进度 |
| 资料理解与分区 | 初始化主智能体 | 基于实际解析内容判断涉及哪些分区，不按模板硬映射 |
| 专项整理 | 五个持久化专项智能体 | 仅使用被分配的数据库交互写各自草稿分区 |
| 跨分区核验 | 平台核验 MCP | 直接读取结构化草稿并执行版本化规则，写入核验问题及 `ready`/`invalid` 状态 |
| 草稿查看与确认 | 工程平台 | 固定界面；用户确认后才原子写入正式项目表 |

初始化不是快速入库状态机，也不是固定格式 ETL。真实模型推理、计划事件、团队邀请、
专项回复和工具调用都由 AgentScope 保留并流式展示。知识库不是默认环节；业务 MCP 只在
任务实际需要时使用，平台核验 MCP 则在草稿各分区完成后自动运行。旧标准化批次、人工分片
和平台确定性字段提取流程不再参与运行。

初始化业务步骤只由下表中的平台技能说明；工程后端不再注入重复流程。团队结构与能力
分配声明在 `AgentScope/project-initialization-team.json`，数据库读取边界和持久化完成
信号由数据库交互目录的 `runtime_policy` 下发，AgentScope 运行器不再按初始化角色写死。

## 固定协作关系

| 智能体 | 技能 | 可写范围 |
| --- | --- | --- |
| Dobby 项目初始化助手 | `orchestrate-project-initialization` | 创建初始化草稿，并在各分区完成后提交草稿编号触发平台核验 |
| 工程信息专家 | `extract-project-basics` | 自己提交的 `project` 分区 |
| 人员与岗位专家 | `organize-project-personnel` | 自己提交的 `personnel` 分区 |
| WBS 与进度专家 | `validate-wbs-timeline` | 自己提交的 `wbs` 分区 |
| 风险源专家 | `extract-project-risks` | 自己提交的 `risks` 分区 |
| 质量指标专家 | `map-quality-requirements` | 自己提交的 `quality_requirements` 分区 |
| 平台核验 MCP | `project-initialization-validator` | 自动读取完整草稿并持久化版本化核验结果；不分配给单个智能体 |
