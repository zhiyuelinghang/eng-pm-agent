---
name: organize-project-personnel
description: 整理项目人员身份、证书、岗位和职责。人员与岗位专家处理系统已有账号复用、身份证去重、同一人员在同一项目承担多个岗位时使用。
---

# 整理人员与岗位

禁止读取原始附件。先调用 `dobby_read_project_initialization_artifact` 读取负责人
指定标准化批次的 `personnel` 分区清单和必要内容；读取具体分片时必须使用
清单中的 `artifact_format`。

## 提取字段

每条任职记录提取：

- `serial_no`
- `real_name`
- `identity_card_no`
- `position_name`
- `certificate_no`
- `responsibility_description`

## 身份与岗位规则

- 以身份证号识别同一自然人。
- 同一身份证号、不同岗位不是重复人员；保留多条任职记录，平台会建立一个账号、
  一个项目成员关系和多个岗位关系。
- 同一身份证号且同一岗位出现多次时仍按原始记录提取，不自行删除或判定重复。
- 姓名相同但身份证号不同不得合并。
- 证书号或职责缺失时保持缺失，不从其他岗位复制。
- 不生成登录账号和密码。平台在草稿确认时负责复用已有账号，或根据姓名生成唯一
  拼音账号和随机初始密码。
- 不判断身份证号、任职、证书或职责是否异常；平台规则和核验智能体统一给出
  校验结论。

## 写入与汇报

核对标准 JSON 是否保留多岗位任职和来源后，调用
`dobby_import_project_initialization_artifact` 批量导入。后端会直接合并标准
资料分片，不要在工具参数中重新复制人员数组。只有少量记录确需修正时，才使用
`dobby_write_project_initialization_draft_section` 提交修正后的完整分区。成功后
用 `TeamSay` 只汇报自然人数、任职数和需统一核验的摘要，不操作账号或正式库。
