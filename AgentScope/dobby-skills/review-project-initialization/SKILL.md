---
name: review-project-initialization
description: 独立读取完整初始化草稿，执行结构与跨分区核验，并完成草稿状态。
---

# 初始化草稿核验

先调用 `dobby_get_project_initialization_draft` 取得草稿 ID、状态和现有问题。分区
数据必须按以下顺序读取，禁止一次返回所有分区的大型 payload：

1. 调用 `dobby_list_project_initialization_sections` 做清单读取，参数必须包含
   `fields=["id","section","revision","source_files","extraction_notes"]` 和
   `limit=20`，确认主智能体任务要求的分区均已提交。
2. `project` 分区是小型对象：使用 `filters={"section":"project"}`，并指定
   `fields=["id","section","payload","source_files","extraction_notes"]`、
   `limit=1` 读取一次。
3. `personnel`、`wbs`、`risks`、`quality_requirements` 的 payload 都是数组，
   必须逐个分区分页读取。每次指定一个明确的 `section` 筛选，并同时指定
   `fields=["id","section","payload","source_files","extraction_notes"]`、
   `limit=1`、`json_field="payload"`、`json_offset=0`、`json_limit=20`。
   读取后检查 `_json_page`：当 `has_more=true` 时，用返回的 `next_offset`
   继续读取同一分区，直至 `has_more=false`；不得遗漏、重复或只读第一页。
4. 如果任何必需分区缺失、某一页返回截断提示、JSON 不完整或分页无法走到
   `has_more=false`，必须继续读取缺失页；仍无法完整读取时只能标记 `invalid`，
   问题中明确记录“分区未完整读取”，绝不能标记 `ready`。

完整读取后核验：

- 必需分区是否与主智能体任务一致；
- 工程日期、合同工期与 WBS 时间范围；
- WBS 编码、直接父级、明确前置关系及质量编码引用；
- 人员身份证号、一人多岗与职责冲突；
- 风险窗口、质量要求及跨分区明显矛盾；
- 每个问题是否保留可核对来源，是否存在无依据补造。

不要重写专家分区，也不要在完成调用里重复提交庞大的合并 payload；平台查看与确认
时会从已持久化分区组合完整草稿。把确定性和语义问题写入
`validation_issues`：存在 error 或任何未完整读取的分区时调用
`dobby_finalize_project_initialization_draft` 标记 `invalid`，否则标记 `ready`。
完成工具成功后即代表核验结果已持久化，平台会自动通知主智能体继续汇总；不要再调用
`TeamSay`，也不要等待第二次汇报。用户确认前不得写正式业务表。
