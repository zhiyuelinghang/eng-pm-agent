---
name: orchestrate-project-initialization
description: 先规划，再组织持久化专项智能体把任意格式资料整理为待用户确认的项目初始化草稿。
---

# 编排项目初始化

附件解析是平台在模型前执行的固定能力。平台把解析结果保存为当前初始化会话的
临时分块；你收到的 `<parsed-attachment-manifest>` 只有文件与 `chunk_id` 清单，
不是正文，更不是固定模板。

## 强制顺序

1. 本轮第一个业务工具调用必须是 `TaskCreate`，计划至少覆盖资料理解、实际涉及
   的业务分区、规则核验和等待用户确认。解析器的前置执行不计入此顺序。
2. 按 manifest 顺序，对每个文件的第一个 chunk 读取首个文本页，以正文判断实际
   分区，不要在主智能体中重复读取全部附件。调用
   `dobby_list_project_initialization_attachment_chunks` 时显式指定 fields，并使用
   `record_id=chunk_id`、`limit=1`、`text_field="content"`、`text_offset=0`、
   `text_limit=6000`；需要完整理解某个分块时，按 `_text_page.next_offset` 继续
   读取到 `has_more=false`。随后调用
   `dobby_get_project_initialization_state` 和
   `dobby_get_project_initialization_draft`，识别增量更新还是新草稿。
3. 需要新草稿时调用 `dobby_create_project_initialization_draft`，传入
   `status="building"`、空的标准 payload、来源文件名，并要求返回新记录以取得
   `draft_id`。不得写正式项目表。平台持久化的解析分块就是本轮附件证据；禁止
   扫描工作区寻找附件或元数据，禁止建立标准化批次、
   写标准化产物或调用任何旧初始化编排 MCP。
4. `TeamCreate` 后只邀请实际涉及的持久化专项智能体。用 `AgentInvite` 的任务说明
   传递 `draft_id`、目标分区、对应 `file_id/chunk_id`、来源文件名和核对要求；
   严禁把解析正文复制进邀请 prompt。不要使用 `AgentCreate`，也不要邀请无关专家。
5. 每位专家完成后，用 `dobby_list_project_initialization_sections` 核对分区确实已
   落入草稿；这里只读取轻量清单，必须显式传入
   `fields=["id","section","revision","source_files","extraction_notes"]`，不得
   一次读取全部 payload。随后用 `TaskUpdate` 更新真实进度。
6. 所需分区全部提交后，直接调用
   `dobby_finalize_project_initialization_draft(record_id=draft_id)`。该调用只提交草稿
   ID；平台会组装已持久化分区并直接运行当前版本的核验 MCP，禁止你重新读取完整
   payload、归纳问题或自行填写 ready/invalid。调用完成后立即调用
   `dobby_get_project_initialization_draft` 读取最终状态和问题。草稿状态为 `ready`
   或 `invalid` 后，更新核验任务与最终汇总任务为完成，结束团队并向用户说明“核对
   草稿”；用户确认才会写正式业务表。

最终汇总必须与草稿状态一致：`ready` 才能说“核验通过”；`invalid` 只能说“核验完成
并发现必须修正的问题”，禁止出现“状态 invalid 但已通过核验”的矛盾表述。

## 资料规则

- 不按文件名、扩展名、工作表位置或历史原型猜字段。
- 缺失值保留 `null`/空数组，数值 `0` 原样保留。
- WBS 编码可以确定层级，不能自动产生前置关系。
- 人员按身份证号识别；同一人员多岗位保留多条任职。
- 冲突值保留来源并形成核对说明，不擅自选择“更合理”的值。
- 知识库不是固定步骤；仅在任务确有需要且已配置相关知识时调用。
