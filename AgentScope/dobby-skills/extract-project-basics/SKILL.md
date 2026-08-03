---
name: extract-project-basics
description: 从工程说明、合同及综合资料中提取项目基础字段。工程信息专家处理工程类型说明、合同日期、工期、金额和五类参建单位时使用。
---

# 提取工程基本信息

禁止读取原始附件。先调用 `dobby_read_project_initialization_artifact` 读取负责人
指定标准化批次的 `project` 分区清单和内容；读取具体分片时必须使用清单中的
`artifact_format`。

## 目标字段

只提取以下字段：

- `engineering_type_description`
- `contract_start_date`
- `contract_end_date`
- `contract_duration_days`
- `contract_amount_wan_yuan`
- `construction_unit_name`
- `general_contractor_unit_name`
- `supervision_unit_name`
- `design_unit_name`
- `survey_unit_name`

项目名称不在初始化范围内，不得提取或修改。

## 提取边界

- 保留日期和金额的原始单位；只有明确换算关系时才转换为目标字段单位。
- 同一字段存在多个来源时逐项列出来源和差异，不自行选择“更合理”的值。
- 空字段保持 `null`，不得增加附件未提供的楼层、面积、项目阶段等字段。
- 不判断合同日期、工期或跨分区数据是否异常；平台规则和核验智能体统一给出
  校验结论。

## 写入与汇报

核对标准 JSON 的字段和来源后，调用
`dobby_import_project_initialization_artifact` 批量导入。后端会直接读取标准
资料，不要在工具参数中重新复制 `project` 对象。只有少量字段确需修正时，才使用
`dobby_write_project_initialization_draft_section` 提交修正后的完整对象。写入
成功后使用 `TeamSay` 只汇报记录已写入、候选值数量和需统一核验的摘要。
