---
name: map-quality-requirements
description: 提取工序质量要求并按 WBS 编码建立确定性关联。质量指标专家处理验收项目、控制指标、检查频次、关联资料及编码无法匹配时使用。
---

# 映射质量指标

禁止读取原始附件。先调用 `dobby_read_project_initialization_artifact` 读取负责人
指定标准化批次的 `quality_requirements` 分区；读取具体分片时必须使用清单中
的 `artifact_format`。草稿 WBS 仅作为编码上下文。

## 提取字段

- `wbs_code`
- `quality_acceptance_item`
- `control_indicator`
- `inspection_frequency`
- `related_documents`

同一 WBS 可对应多条质量要求，不能合并丢失。

## 提取边界

- 只按附件明确的 WBS 编码关联。
- WBS 编码缺失时保留原值；禁止用名称相似度猜测。
- 验收项目、控制指标、检查频次或关联资料缺失时保持缺失，不生成通用模板文本。
- 重复出现的原始记录不得在提取阶段自行删除。
- 表头合并、跨行内容或 OCR 结果不确定时列出原始行和证据位置。
- 不判断编码是否存在、记录是否重复或质量内容是否异常；平台规则和核验智能体
  统一给出结论。

## 写入与汇报

核对标准 JSON 的质量字段、WBS 编码和来源后，调用
`dobby_import_project_initialization_artifact` 批量导入。后端会直接合并标准
资料分片，不要在工具参数中重新复制质量数组。只有少量记录确需修正时，才使用
`dobby_write_project_initialization_draft_section` 提交修正后的完整分区。成功后
用 `TeamSay` 只汇报指标数和需统一核验的摘要。
