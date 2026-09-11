---
name: organize-project-personnel
description: 整理人员与岗位记录，并写入自己负责的初始化草稿分区。
---

# 人员与岗位草稿分区

只处理 `section="personnel"`。每条任职包含序号、姓名、身份证号、岗位、证书和
职责。同一身份证号的不同岗位必须保留多条；不得生成账号或密码。

`position_name` 按原始资料逐字采集，不套用固定岗位范围、不替换相近岗位。
岗位是否有效、姓名与账号是否一致，均由核验 MCP 判定。

邀请任务只包含相关 `file_id/chunk_id`。先用
`dobby_list_project_initialization_attachment_chunks` 逐个读取分块，显式指定 fields，并
使用 `record_id=chunk_id`、`limit=1`、`text_field="content"`、`text_offset=0`、
`text_limit=6000`。每页检查 `_text_page`，用 `next_offset` 继续读取，直到
`has_more=false`；必须读完所有相关分块，禁止只读第一页。
随后按需调用 `dobby_get_project_initialization_state(section="personnel", offset=0, limit=20)`
读取当前项目正式任职，依 `page.next_offset` 分页，再读取当前草稿和分区。新分区调用
`dobby_create_initialization_personnel_section`；已有自己提交的分区调用
`dobby_update_initialization_personnel_section`。写入本次草稿人员数组、来源文件和
来源说明，不写正式业务表。`payload` 顶层必须直接是人员数组，禁止再包裹
`personnel`、`items`、`data`、`result` 或 `summary`。写入成功就是完成边界，
无需再调用 `TeamSay`。每条记录的字段名必须逐字使用写入工具 schema 中的英文技术
字段，禁止中文字段名和 schema 外字段。

身份证号和岗位用作匹配线索，其他字段仅写本次资料明确给出的内容；
未识别字段省略，不填 `null`，不把旧人员未出现在附件中当作删除。更新草稿分区时
保留该分区已提取的其他记录，不把正式人员全量抄入草稿。最终人员匹配、新旧差异和
资料必填、空值及合格性全部由当前核验 MCP 判定；完成本分区即可提交，不等其他分区齐全。

`source_files` 必须非空并明确记录本次使用的 `file_id/chunk_id` 与文件名；
`extraction_notes` 只记录来源位置、读取情况和格式转换，不生成资料问题或合格性结论，没有说明时传空数组。
提交前确认 notes 与最终 payload 一致，禁止写通用免责声明或推测。

资料是否合格、哪些字段必填、能否留空以及本批次问题范围，全部由当前核验 MCP 决定；智能体和前后端不得另设业务判定，也不得擅自要求质量空白字段补齐。

## 初始化智能体职责边界

只读取用户上传的资料、提取原始内容并形成草稿。资料是否正确、完整、重复、匹配、必填或允许留空，全部交给平台当前绑定的核验 MCP；不得自己核验，不得把自己的判断写进 extraction_notes 或向用户作为核验结论输出。只可原样转述 MCP 的结论。发现问题后由用户人工修改原始资料并重新上传，智能体不得代为修正。
