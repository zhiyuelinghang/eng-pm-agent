---
name: map-quality-requirements
description: 整理工序质量指标，并写入自己负责的初始化草稿分区。
---

# 质量指标草稿分区

只处理 `section="quality_requirements"`：WBS 编码、验收项目、控制指标、检查频次
和关联资料。只保留资料明确给出的编码，不按名称相似度补关联。

邀请任务只包含相关 `file_id/chunk_id`。用解析分块读取交互逐个读取分块，显式指定
fields，并使用 `record_id=chunk_id`、`limit=1`、`text_field="content"`、
`text_offset=0`、`text_limit=6000`。每页检查 `_text_page`，用 `next_offset`
继续读取，直到 `has_more=false`；必须读完所有相关分块，禁止只读第一页。随后再读取
当前草稿和分区。
新分区调用 `dobby_create_initialization_quality_section`；
已有自己提交的分区调用 `dobby_update_initialization_quality_section`。写入完整数组、
来源和待核对编码，不写正式业务表。`payload` 顶层必须直接是质量指标数组，禁止再
包裹 `quality_requirements`、`items`、`data`、`result` 或 `summary`。写入成功就是
完成边界，无需再调用 `TeamSay`。每条记录的字段名必须逐字使用写入工具 schema
中的英文技术字段，禁止中文字段名和 schema 外字段。

`source_files` 必须非空并明确记录本次使用的全部 `file_id/chunk_id` 与文件名；
`extraction_notes` 只记录原文中实际存在的空汇总行、重复或编码疑点，没有疑点时
传空数组。证据映射不得只保留在邀请任务中，提交前确认 notes 与最终 payload 一致。
