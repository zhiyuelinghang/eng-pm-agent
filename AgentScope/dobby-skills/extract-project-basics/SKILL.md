---
name: extract-project-basics
description: 从主智能体提供的解析证据整理工程基本信息，并写入自己负责的初始化草稿分区。
---

# 工程信息草稿分区

只处理 `section="project"`：工程类型说明、合同日期、合同工期、合同金额和参建
单位。项目名称由用户创建，不在此分区修改。

邀请任务只包含相关 `file_id/chunk_id`。逐个调用
`dobby_list_project_initialization_attachment_chunks`，显式指定 fields，并使用
`record_id=chunk_id`、`limit=1`、`text_field="content"`、`text_offset=0`、
`text_limit=6000`。每页检查 `_text_page`，用 `next_offset` 继续读取，直到
`has_more=false`；必须读完所有相关分块，禁止只读第一页。
随后再读取当前草稿和分区。新分区调用
`dobby_create_initialization_project_section`；已有自己提交的分区调用
`dobby_update_initialization_project_section`。写入 `draft_id`、标准字段 payload、
来源文件名与冲突/缺失说明；不要写正式业务表。`payload` 顶层必须直接是工程信息
对象，禁止再包裹 `project`、`data`、`result` 或 `summary`。写入成功就是完成边界，无需再调用
`TeamSay`。字段名必须逐字使用写入工具 schema 中的英文技术字段，禁止中文字段名和
schema 外字段。缺失值用 `null`，同一字段冲突时保留来源，不自行取舍。

`source_files` 必须非空并明确记录本次使用的 `file_id/chunk_id` 与文件名；
`extraction_notes` 只记录原文中实际存在的冲突、缺失或转换，没有疑点时传空数组。
提交前逐项对照 payload：已经填入的字段绝不能再写成“原文未提及”或“保留 null”；
禁止把示例字段、通用免责声明或推测写进 notes。
