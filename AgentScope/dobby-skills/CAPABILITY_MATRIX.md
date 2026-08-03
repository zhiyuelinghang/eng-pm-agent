# Dobby 初始化智能体能力清单

## 工具能力

| 能力 | 受控工具 | 当前支持 |
| --- | --- | --- |
| 初始化状态 | `dobby_get_project_initialization_state` | 正式数据摘要、最新草稿摘要、当前会话附件 |
| 草稿读取 | `dobby_get_project_initialization_draft` | 按分区分页读取工程信息、人员、WBS、风险、质量 |
| 原始附件读取 | `dobby_read_project_initialization_file` | XLS/XLSX、CSV、DOCX、PPTX、PDF、图片、TXT、Markdown |
| 表格保真 | 原始附件读取工具 | 数值 0/空值、合并单元格、公式与缓存值、工作表、分页 |
| 文档结构 | 原始附件读取工具 | DOCX 段落和表格原始顺序、PPTX 页内文本与表格 |
| PDF | 原始附件读取工具 | 文本层、表格、无文本扫描页本地 OCR |
| 图片 | 原始附件读取工具 | 本地 OCR、置信度、文字坐标 |
| 标准化批次 | `dobby_begin_project_initialization_normalization` | 主智能体登记本轮原始附件 |
| 标准资料写入 | `dobby_write_project_initialization_artifact` | 主智能体按业务分区写规范 JSON 或 Markdown；结构化分区先单条试写，再按每批最多 20 条写入 |
| 标准资料封存 | `dobby_finalize_project_initialization_normalization` | 校验字段和分片，返回 `ready` 后才允许分配 |
| 标准资料读取 | `dobby_read_project_initialization_artifact` | 专家按分区、分片分页读取 JSON/Markdown |
| 初始化任务 | `dobby_begin_project_initialization_draft` | 使用 ready 批次声明本轮实际涉及的分区 |
| 专项批量导入 | `dobby_import_project_initialization_artifact` | 后端合并 JSON 分片并直接写入专家绑定分区 |
| 专项修正写入 | `dobby_write_project_initialization_draft_section` | 仅在少量数据确需修正时整体替换专家分区 |
| 统一核验 | `dobby_finalize_project_initialization_draft` | 核验专家补充语义问题，平台执行确定性规则并汇总草稿 |
| 计划和团队 | `TaskCreate`、`TaskUpdate`、`AgentInvite`、`TeamSay` | 仅在标准化 ready 后按需计划和协同 |

平台与 AgentScope 管理端均禁用 PowerShell 和其他宿主机命令执行工具。附件读取、
数据查询和草稿维护不得回退到命令行。

## 技能分配

| 智能体 | 分配技能 |
| --- | --- |
| Dobby 项目初始化助手 | `read-initialization-attachments`、`orchestrate-project-initialization` |
| 工程信息专家 | `extract-project-basics` |
| 人员与岗位专家 | `organize-project-personnel` |
| WBS 与进度专家 | `validate-wbs-timeline` |
| 风险源专家 | `extract-project-risks` |
| 质量指标专家 | `map-quality-requirements` |
| 初始化核验专家 | `review-project-initialization` |

全局总控和其他业务智能体不自动获得项目初始化技能。

## 职责链路

1. 初始化主智能体读取原始附件，拆分业务分区并写入规范 JSON/Markdown。
2. 标准资料全部通过校验后，主智能体才建立草稿任务、计划和临时团队。
3. 对应的持久化专项智能体读取标准资料，并调用后端批量导入工具写自己唯一
   拥有的草稿分区；专项智能体不读取原始附件。
4. 专项智能体只记录来源和无法识别的原始证据，不做最终异常判定。
5. 所有本轮分区完成后，平台规则引擎执行确定性校验；初始化核验专家补充
   跨专业语义问题并完成统一汇总。
6. 主智能体只根据 workflow 汇报进度和最终结果；用户在平台确认后才写正式表。

单一附件不固定启动全部专家：人员附件只处理 `personnel`，质量附件只处理
`quality_requirements`。质量分区可以读取已有草稿 WBS 作为编码上下文，并在
最终核验阶段判断关联错误；风险分区只保留相关工序文字和风险窗口，不关联 WBS。

## 已知边界

- 不支持旧版二进制 Word `.doc`、PowerPoint `.ppt`、Microsoft Project `.mpp`、
  CAD/BIM 模型、压缩包、音视频和邮件容器。
- 不解密有密码的文档，不执行 Office 宏，也不重新计算 Excel 公式。
- OCR 适合印刷体和清晰扫描件；手写、倾斜、低清或复杂工程图纸必须提示人工核对。
- PDF 表格提取依赖文档结构；无边框、跨页或复杂合并表格可能只能返回 OCR 文本。
- 工具只处理单个不超过 30MB 的附件；大文件必须依照 `next_start` 分段读取。
- 技能负责工作方法和领域规则，不能替代工具权限、数据库事务和平台校验。
- 主智能体负责读取与标准化原始输入；专项专家只核对标准资料并触发后端批量
  导入，避免用团队消息或工具参数传输大批数据。
