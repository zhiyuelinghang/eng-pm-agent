---
name: validate-wbs-timeline
description: 完整提取阶段式 WBS 树、计划字段及附件明确给出的前置关系。WBS 与进度专家处理进度计划或 Project 导出表时使用。
---

# 提取 WBS 与进度

禁止读取原始附件。先调用 `dobby_read_project_initialization_artifact` 读取负责人
指定标准化批次的 `wbs` 分区清单，并使用清单中的 `artifact_format` 按分片
分页核对必要内容。

## 构建记录

保留附件中每条带 WBS 编码的记录，并提取草稿结构要求的全部原始字段。核心规则：

- `level` 等于点分编码段数。
- `parent_wbs_code` 只能是直接编码前缀；根节点为 `null`。
- `sort_order` 按原始行顺序或明确排序字段保留。
- `progress_percent=0` 必须保留为 `0`；空单元格才是 `null`。
- 状态、优先级、日期为空时保持 `null`，不得写“未提供”。
- `predecessor_wbs_codes` 只来自附件明确的前置字段或用户明确说明；禁止依据相邻
  编码、名称或日期推断。
- 名称像“任务名称”等占位内容时仍保留记录，同时标记疑似占位。

## 职责边界

- 只提取字段、构造直接父级和保留附件明确给出的前置关系。
- 不判断编码重复、父级缺失、时间线、依赖、汇总日期或占位内容是否异常。
- 平台规则统一检查可确定的结构和时间问题；初始化核验专家负责跨专业语义问题。
- 遇到无法读取的单元格或多个互相冲突的原始值时保留证据，不自行修正。

## 写入与汇报

核对标准 JSON 的编码、层级、0/空值和来源后，调用
`dobby_import_project_initialization_artifact` 批量导入。后端会直接合并全部
JSON 分片，不要在工具参数中重新生成或复制完整 WBS。只有少量节点确需修正时，
才使用 `dobby_write_project_initialization_draft_section` 提交修正后的完整分区。
成功后用 `TeamSay` 只汇报节点数和需统一核验的摘要。
