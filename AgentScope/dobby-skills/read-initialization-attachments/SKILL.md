---
name: read-initialization-attachments
description: 可靠读取项目初始化附件并保留可核对证据。处理 XLS/XLSX、CSV、DOCX、PPTX、PDF、图片、TXT 或 Markdown 时使用，尤其适用于多工作表、大文件分页、扫描件 OCR、表格合并单元格、公式及空值识别。
---

# 读取初始化附件

此技能只分配给初始化主智能体。只通过
`dobby_read_project_initialization_file` 读取附件；专项智能体不得使用本技能
或接触原始附件。禁止使用 PowerShell、Shell、Python 执行器或工作区文件命令
绕过该工具。

## 读取流程

1. 先调用 `dobby_get_project_initialization_state`，取得本会话授权的
   `file_id`、文件名和最新草稿摘要。
2. 按文件结构读取：
   - XLS/XLSX：先读取默认工作表并检查 `sheet_names`，再逐个读取相关工作表。
   - CSV/TXT/Markdown：按 `start`、`limit` 分段。
   - DOCX：按文档块顺序读取，表格块与段落顺序不得打乱。
   - PPTX：按页读取文本、表格和图片 OCR。
   - PDF：按页读取文本、表格；扫描页使用 `ocr_mode=auto`。
   - 图片：使用 `ocr_mode=auto` 读取文字、置信度和坐标。
3. 只要返回 `next_start`，继续读取，直到覆盖任务所需范围。不得看完首段就
   声称已完整读取。
4. 判断每段内容属于工程信息、人员、WBS、风险源、质量指标中的哪些分区；
   同一文件可以拆成多个业务分区，不能假设“一份附件只对应一类数据”。
5. 输出每条结论的文件名、工作表与行号，或页码、文档块位置。

## 数据保真

- 数值 `0` 是真实值；只有原始空单元格才是 `null`。
- 保留原始文本、日期、编码、状态和优先级，不自行改写。
- 对公式同时查看 `formula` 与 `cached_value`；缓存为空时把公式标记为待核对，
  不计算或猜测结果。
- 对 `merged_ranges` 只把左上角值视为合并区域原值。
- OCR 置信度低、文字断裂或表格结构不确定时，保留识别文本并明确提示人工核对。
- 文件损坏、加密、格式不受支持或 OCR 失败时，报告具体限制并请用户换文件；
  不切换到命令行读取。

## 输出要求

读取完成后，通过 `dobby_write_project_initialization_artifact` 写标准资料：

- 可批量入草稿的业务数据必须使用平台规范 JSON；
- 叙述、证据和补充说明可以使用 Markdown；
- 每份资料只属于一个业务分区；
- 除工程信息外，先用 `part_index=1` 且只提交 1 条记录试写；必须等待
  `probe_accepted`，失败时只修正这一条，不得预先生成其余批次；
- 试写成功后从 `part_index=2` 开始连续分片，每批最多 20 条且不超过 64KB；
- 只使用工具参数声明的标准字段名，禁止自行创造字段别名；
- 写入原始 `file_id` 和工作表、行号、页码或段落等来源。

所有本轮分区完成后调用
`dobby_finalize_project_initialization_normalization`。只有返回 `ready` 后才把
`normalization_id` 交给专项智能体。不要直接写正式库，也不要把附件中不存在的
字段补成常识值。
