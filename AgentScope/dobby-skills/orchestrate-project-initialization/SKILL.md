---
name: orchestrate-project-initialization
description: 读取项目正式现状，按实际资料组织专项智能体生成可分批确认的新增或更新草稿。
---

# 编排项目初始化

附件解析是平台在模型前执行的固定能力。平台把解析结果保存为当前初始化会话的
临时分块；你收到的 `<parsed-attachment-manifest>` 只有文件与 `chunk_id` 清单，
不是正文，更不是固定模板。

## 强制顺序

1. 使用简体中文说明进度、协同反馈和最终结果。不创建执行计划，不调用任务创建、
   查询或更新工具；进度由真实专家状态和草稿分区状态展示。
2. 按 manifest 顺序，对每个文件的第一个 chunk 读取首个文本页，以正文判断实际
   分区，不要在主智能体中重复读取全部附件。调用
   `dobby_list_project_initialization_attachment_chunks` 时显式指定 fields，并使用
   `record_id=chunk_id`、`limit=1`、`text_field="content"`、`text_offset=0`、
   `text_limit=6000`。即使已传唯一的 `record_id` 也绝不能省略 `limit=1`，否则
   平台会拒绝调用；需要完整理解某个分块时，按 `_text_page.next_offset` 继续
   读取到 `has_more=false`。随后调用
   `dobby_get_project_initialization_state(section="overview")` 读取当前项目正式
   数据概况，再用 `dobby_get_project_initialization_draft` 读取当前会话草稿。
   正式现状不受会话边界限制，草稿与正式现状不是同一份数据。只按实际涉及分区
   调用 state 的 `section`、`offset`、`limit<=20` 读取必要旧数据，可传 `fields`
   缩小字段；依 `page.next_offset` 分页，禁止一次索取五类完整数据或将其塞入 prompt。
   据此说明本次可能是新增、补充更新或无变化；最终匹配、字段差异和冲突由平台预览
   计算，不凭模型判断覆盖正式旧值。
3. 需要新草稿时调用 `dobby_create_project_initialization_draft`，只在 `values` 中
   传入非空 `source_files`，并设置 `return_record=true` 取得新记录的 `draft_id`；
   `status`、`payload`、会话和创建人均由平台生成，禁止传入。不得写正式项目表。
   平台持久化的解析分块就是本轮附件证据；禁止
   扫描工作区寻找附件或元数据，禁止建立标准化批次或写标准化产物。
   当前会话有多个草稿时显式按 `id` 倒序只读一条，取得 `draft_id` 后后续读取都按
   `record_id=draft_id` 定位；不要把项目其他会话的最新草稿当作本次草稿。
   草稿已 `applied` 或 `rejected` 时，本次上传必须新建草稿，不能继续修改已结束草稿。
4. `TeamCreate` 后只邀请实际涉及的持久化专项智能体。用 `AgentInvite` 的任务说明
   传递 `draft_id`、目标分区、对应 `file_id/chunk_id`、来源文件名和核对要求；
   严禁把解析正文复制进邀请 prompt。不要使用 `AgentCreate`，也不要邀请无关专家。
5. 每位专家完成后，用 `dobby_list_project_initialization_sections` 核对分区确实已
   落入草稿；这里只读取轻量清单，必须显式传入
   `fields=["id","section","revision","source_files","extraction_notes"]`，不得
   一次读取全部 payload。用简洁中文说明已完成分区和仍在等待的专家。
   已有可用分区时及时核验并告知用户可核对该部分，剩余专家继续整理；不要因为资料
   没有其他分区而等待五类齐全。不要创建没有资料的空分区来凑齐数量。
6. 可用分区提交后，直接调用
   `dobby_finalize_project_initialization_draft(record_id=draft_id)`。该调用只提交草稿
   ID；平台会组装已持久化分区并直接运行当前版本的核验 MCP，禁止你重新读取完整
   payload、归纳问题或自行填写 ready/invalid。调用完成后立即调用
   `dobby_get_project_initialization_draft` 读取最终状态和问题。草稿状态为 `ready`
   或 `invalid` 后，向用户说明“核对草稿”，以及有正式旧数据
   时可查看“新旧差异”。某分区的问题不应描述为其他可用分区也不能确认。后续有新
   分区或草稿修订时再次核验；本轮涉及分区全部整理结束后才结束团队并汇总。
   用户可以只确认已有可用分区；用户确认才会写正式业务表。
   核验发现的问题原样交由用户查看；只能由用户修改原始资料后重新上传。
   不得自行修复、删改问题记录、补齐字段或生成新的业务核验结论。

最终汇总必须与草稿状态一致：`ready` 才能说“核验通过”；`invalid` 只能说“核验完成
并发现必须修正的问题”，禁止出现“状态 invalid 但已通过核验”的矛盾表述。

## 资料规则

- 不按文件名、扩展名、工作表位置或历史原型猜字段。
- 未提供分区保持原状；记录只写资料明确给出的字段，未识别字段省略，数值 `0`
  原样保留。不要用 `null` 或空数组填补缺失字段，不把附件没出现的旧记录推断为删除。
- 人员以身份证号和岗位、WBS 与质量以 WBS 编码、风险以相关工序和风险部位作为
  匹配线索；不要以序号或近似名称强行匹配。平台负责最终匹配；资料是否合格、哪些
  字段必填、能否留空及本批次问题范围，全部由当前核验 MCP 决定，不另设判断。
- WBS 编码可以确定层级，不能自动产生前置关系。
- 人员按身份证号识别；同一人员多岗位保留多条任职。
- 冲突值保留来源并形成来源说明，不擅自选择“更合理”的值。
- 知识库不是固定步骤；仅在任务确有需要且已配置相关知识时调用。

资料是否合格、哪些字段必填、能否留空以及本批次问题范围，全部由当前核验 MCP 决定；智能体和前后端不得另设业务判定，也不得擅自要求质量空白字段补齐。

## 初始化智能体职责边界

只读取用户上传的资料、提取原始内容并形成草稿。资料是否正确、完整、重复、匹配、必填或允许留空，全部交给平台当前绑定的核验 MCP；不得自己核验，不得把自己的判断写进 extraction_notes 或向用户作为核验结论输出。只可原样转述 MCP 的结论。发现问题后由用户人工修改原始资料并重新上传，智能体不得代为修正。
