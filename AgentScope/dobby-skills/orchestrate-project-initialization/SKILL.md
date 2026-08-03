---
name: orchestrate-project-initialization
description: 编排 Dobby 项目初始化全过程。初始化主智能体处理多附件、多业务分区、专项协同、交叉校验、草稿提交或增量修订时使用；简单问答不触发形式化计划和团队。
---

# 编排项目初始化

项目名称由用户创建，禁止修改。初始化结果先进入待核对草稿，只有用户在平台确认
后才写入正式业务表。

## 判断复杂度

- 单字段查询、解释已有结果或单步读取：直接完成。
- 任何需要写入草稿的任务都先标准化原始输入；标准化完成前不创建计划或团队。
- 标准化完成后，多业务分区、批量数据、跨表关联或专项并行任务使用
  `TaskCreate`/`TaskUpdate` 建立简洁计划。
- 标准化完成后，只要需要写入或更新任一草稿分区，就创建临时团队，并通过
  `AgentInvite` 邀请该分区对应的现有专项专家；即使只有一个分区也必须邀请，
  主智能体不得代写。全部实际分区完成后再邀请初始化核验专家。禁止临时创建替身。

## 执行顺序

1. 调用 `dobby_get_project_initialization_state`，区分正式数据、待核对草稿和附件。
2. 若已有草稿，调用 `dobby_get_project_initialization_draft` 读取本轮涉及的旧
   分区，增量数据必须与旧分区合并为完整结果。
3. 调用 `dobby_begin_project_initialization_normalization` 建立标准化批次。
   初始化主智能体逐个读取任意格式原始附件；一份文件可以包含多个工作表、页面、
   段落和业务分区，不能依赖固定模板或文件扩展名判断内容。
4. 将内容拆成 `project`、`personnel`、`wbs`、`risks`、
   `quality_requirements`。通过
   `dobby_write_project_initialization_artifact` 写入标准资料：结构化入草稿
   数据必须是平台规范 JSON；叙述与证据可以是 Markdown。除工程信息外，
   每个分区先用 `part_index=1` 只提交 1 条记录，等待 `probe_accepted`；
   失败时只修正首条，禁止预先生成剩余数据。成功后从 `part_index=2` 开始
   连续分片，每批最多 20 条且不超过 64KB。只能使用工具声明的标准字段名。
   这里写入的 artifact 只是标准化中间资料，不是业务草稿或正式业务入库。
5. 调用 `dobby_finalize_project_initialization_normalization`。只有返回
   `ready` 后才允许创建计划、团队和草稿任务。
6. 根据标准化结果决定本轮实际分区，调用
   `dobby_begin_project_initialization_draft` 并传入 `normalization_id`。只上传
   人员资料就只填写 `personnel`；只上传质量资料就只填写
   `quality_requirements`，禁止固定要求五个分区全部重跑。
7. 必须创建临时团队并邀请 `expected_sections` 对应的专项专家。给每个专家仅
   指定 `normalization_id`、`draft_id`、业务分区和核对要求，不发送原始附件。
   即使只有一个分区也必须邀请对应专家；主智能体不得直接写草稿分区。
8. 专项专家读取标准资料，并用
   `dobby_import_project_initialization_artifact` 让后端合并 JSON 分片并批量导入
   自己唯一拥有的草稿分区。读取具体分片时必须传 `artifact_format`；禁止在
   TeamSay 或工具参数里重新复制整批 JSON。
9. 持续读取草稿 workflow。只有本轮 `expected_sections` 全部进入
   `completed_sections`，才邀请初始化核验专家。
10. 初始化核验专家读取完整草稿，补充跨专业语义问题，并调用
   `dobby_finalize_project_initialization_draft`。平台同时执行确定性结构、编码、
   时间、重复和关联规则。
11. 最终核验完成后同步计划状态并结束团队；向用户摘要问题，并提示进入
   “核对草稿”。用户确认前不得声称已入正式库。

## 约束

- 不使用 PowerShell、Shell、Python 执行器或直接数据库操作。
- 原始附件只允许初始化主智能体读取；专项和核验智能体只读取标准资料或草稿。
- 标准化未返回 `ready` 时，禁止 `TaskCreate`、`TeamCreate`、`AgentInvite`
  和草稿任务建立。
- 主智能体负责原始资料标准化，但不直接修改任何业务草稿分区。
- 初始化主智能体只能使用初始化读取、标准化和编排工具，不得调用普通业务写入
  或管理员正式业务写入工具。
- 专项专家只能写自己持久化角色绑定的分区，不能修改其他分区。
- 核验专家不能重新提取附件或代替专项专家补录数据。
- 不因正式库为空而忽略已有草稿，也不重复解析与本次无关的旧附件。
- 任何错误、冲突、时间线异常或无法匹配项都保留原值，并提示用户进入“核对草稿”
  查看和确认。
- 不以“已派发”“TeamSay 已返回”或“成员回复结束”作为分区完成依据；只有
  workflow 与最终核验状态是事实来源。
