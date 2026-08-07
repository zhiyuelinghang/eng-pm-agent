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
当前草稿和分区。
新分区调用 `dobby_create_initialization_risks_section`；已有
自己提交的分区调用 `dobby_update_initialization_risks_section`。写入完整数组、来源
和核对说明，不写正式业务表。`payload` 顶层必须直接是风险数组，禁止再包裹
`risks`、`items`、`data`、`result` 或 `summary`。写入成功就是完成边界，无需再
调用 `TeamSay`。每条记录的字段名必须逐字使用写入工具 schema 中的英文技术字段，
禁止中文字段名和 schema 外字段。

`source_files` 必须非空并明确记录本次使用的 `file_id/chunk_id` 与文件名；
`extraction_notes` 只记录原文中实际存在的跳号、冲突或日期转换，没有疑点时传空数组。
证据映射不得只保留在邀请任务中，提交前确认 notes 与最终 payload 一致。
