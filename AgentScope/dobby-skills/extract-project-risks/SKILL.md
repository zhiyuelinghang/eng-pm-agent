---
name: extract-project-risks
description: 整理风险源记录，并写入自己负责的初始化草稿分区。
---

# 风险源草稿分区

只处理 `section="risks"`：序号、相关工序原文、风险部位、等级、判定条件、风险
起止日期和摘要。风险源不自动关联 WBS，也不擅自改写风险等级。

邀请任务只包含相关 `file_id/chunk_id`。用解析分块读取交互逐个读取分块，显式指定
fields，并使用 `record_id=chunk_id`、`limit=1`、`text_field="content"`、
`text_offset=0`、`text_limit=6000`。每页检查 `_text_page`，用 `next_offset`
继续读取，直到 `has_more=false`；必须读完所有相关分块，禁止只读第一页。随后再读取
当前草稿和分区；按需调用 `dobby_get_project_initialization_state(section="risks", offset=0, limit=20)`
读取正式旧数据，依 `page.next_offset` 分页。
新分区调用 `dobby_create_initialization_risks_section`；已有
自己提交的分区调用 `dobby_update_initialization_risks_section`。写入本次草稿数组、来源
和来源说明，不写正式业务表。`payload` 顶层必须直接是风险数组，禁止再包裹
`risks`、`items`、`data`、`result` 或 `summary`。写入成功就是完成边界，无需再
调用 `TeamSay`。每条记录的字段名必须逐字使用写入工具 schema 中的英文技术字段，
禁止中文字段名和 schema 外字段。

相关工序原文和风险部位用作匹配线索，不用序号判断是否同一风险。其他字段只写
本次资料明确给出的内容，未识别字段省略，不填 `null`。更新草稿保留该分区已提取
的其他记录，不复制全部正式旧风险，不把附件缺行当作删除。平台负责新旧匹配、
差异展示；资料必填、空值及合格性全部由当前核验 MCP 判定；完成本分区即可提交，不等其他分区齐全。

`source_files` 必须非空并明确记录本次使用的 `file_id/chunk_id` 与文件名；
`extraction_notes` 只记录来源位置、读取情况和日期格式转换，不判断原表序号或时间是否正确，没有说明时传空数组。
证据映射不得只保留在邀请任务中，提交前确认 notes 与最终 payload 一致。

资料是否合格、哪些字段必填、能否留空以及本批次问题范围，全部由当前核验 MCP 决定；智能体和前后端不得另设业务判定，也不得擅自要求质量空白字段补齐。

## 初始化智能体职责边界

只读取用户上传的资料、提取原始内容并形成草稿。资料是否正确、完整、重复、匹配、必填或允许留空，全部交给平台当前绑定的核验 MCP；不得自己核验，不得把自己的判断写进 extraction_notes 或向用户作为核验结论输出。只可原样转述 MCP 的结论。发现问题后由用户人工修改原始资料并重新上传，智能体不得代为修正。
