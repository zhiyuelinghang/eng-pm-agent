---
name: extract-project-risks
description: 从工程风险清单提取风险要素。风险源专家处理相关工序、风险等级、部位、判定条件和风险窗口时使用。
---

# 提取项目风险源

禁止读取原始附件。先调用 `dobby_read_project_initialization_artifact` 读取负责人
指定标准化批次的 `risks` 分区；读取具体分片时必须使用清单中的
`artifact_format`。风险源不关联 WBS，不读取草稿 WBS，也不推断 WBS 编码。

## 提取字段

- `serial_no`
- `related_process_name`
- `risk_part`
- `risk_level`
- `evaluation_condition`
- `risk_window_start_date`
- `risk_window_end_date`
- `summary`

## 提取规则

- `related_process_name` 忠实保留风险清单中的相关工序文字，不转换为 WBS。
- 风险窗口由 `risk_window_start_date` 和 `risk_window_end_date` 表达；原文缺失时使用 `null`。
- 序号缺口不等于数据缺失；只报告实际读取到的记录和来源范围。
- 不判断时间窗口、等级或判定条件是否异常；平台规则和核验
  智能体统一给出结论。

## 写入与汇报

核对标准 JSON 的风险字段、相关工序、风险窗口和来源后，调用
`dobby_import_project_initialization_artifact` 批量导入。后端直接读取标准资料，
不要在工具参数中重新复制风险数组。只有少量记录确需修正时，才使用
`dobby_write_project_initialization_draft_section` 提交修正后的完整分区。成功后
用 `TeamSay` 只汇报风险数和需统一核验的摘要。
