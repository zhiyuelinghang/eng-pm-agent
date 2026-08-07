---
name: organize-project-personnel
description: 整理人员与岗位记录，并写入自己负责的初始化草稿分区。
---

# 人员与岗位草稿分区

只处理 `section="personnel"`。每条任职包含序号、姓名、身份证号、岗位、证书和
职责。同一身份证号的不同岗位必须保留多条；不得生成账号或密码。

邀请任务只包含相关 `file_id/chunk_id`。先用
`dobby_list_project_initialization_attachment_chunks` 逐个读取分块，显式指定 fields，并
使用 `record_id=chunk_id`、`limit=1`、`text_field="content"`、`text_offset=0`、
`text_limit=6000`。每页检查 `_text_page`，用 `next_offset` 继续读取，直到
`has_more=false`；必须读完所有相关分块，禁止只读第一页。
随后再读取当前草稿和分区。新分区调用
`dobby_create_initialization_personnel_section`；已有自己提交的分区调用
`dobby_update_initialization_personnel_section`。写入完整人员数组、来源文件和
核对说明，不写正式业务表。`payload` 顶层必须直接是人员数组，禁止再包裹
`personnel`、`items`、`data`、`result` 或 `summary`。写入成功就是完成边界，
无需再调用 `TeamSay`。每条记录的字段名必须逐字使用写入工具 schema 中的英文技术
字段，禁止中文字段名和 schema 外字段。

`source_files` 必须非空并明确记录本次使用的 `file_id/chunk_id` 与文件名；
`extraction_notes` 只记录原文中实际存在的冲突、缺失或转换，没有疑点时传空数组。
提交前确认 notes 与最终 payload 一致，禁止写通用免责声明或推测。
