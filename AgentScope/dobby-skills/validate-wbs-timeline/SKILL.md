---
name: validate-wbs-timeline
description: 整理 WBS、计划与进度，并写入自己负责的初始化草稿分区。
---

# WBS 与进度草稿分区

只处理 `section="wbs"`。保留本次资料明确提供的编码、名称、日期、工时、进度、状态、
优先级、成本和来源；未提供字段省略。`parent_wbs_code` 只能由直接编码前缀确定；前置编码只能来自资料明确
说明；数值 `0` 不是空值。

必须逐列核对原表与提交 payload，不能只提取编码、名称、日期等主要字段。原表中存在的列按以下
对应关系完整保留：优先级→`priority_text`，预计小时数→`estimated_hours`，时间日志（分钟）→
`time_log_minutes`，预算→`budget`，实际成本→`actual_cost`，MSP UID→`msp_uid`，MSP ID→
`msp_id`，创建于→`source_created_at`，创建者→`source_creator`，类型→`item_type`，项目路径→
`source_project_path`。其中预计小时数、时间日志、预算、实际成本即使整列为 0 也必须逐行保留。
不得把上述已识别列视为“不重要的附加信息”省略；提交前核对每个非空源单元格均有对应字段。
若工具 schema 无法承载原表某一列，明确记入 `extraction_notes`，不能声称已完整提取。

邀请任务只包含相关 `file_id/chunk_id`。用解析分块读取交互逐个读取分块，显式指定
fields，并使用 `record_id=chunk_id`、`limit=1`、`text_field="content"`、
`text_offset=0`、`text_limit=6000`。每页检查 `_text_page`，用 `next_offset`
继续读取，直到 `has_more=false`；必须读完所有相关分块，禁止只读第一页。随后再读取
当前草稿和分区；按需调用 `dobby_get_project_initialization_state(section="wbs", offset=0, limit=20)`
读取正式旧数据，依 `page.next_offset` 分页。
新分区调用 `dobby_create_initialization_wbs_section`；已有
自己提交的分区调用 `dobby_update_initialization_wbs_section`。写入本次草稿数组、来源
和时间线/层级来源位置，不写正式业务表。`payload` 顶层必须直接是 WBS 数组，禁止
再包裹 `wbs`、`tasks`、`items`、`data`、`result` 或 `summary`。数组必须保持扁平，
每行资料对应一条记录，层级只写入 `parent_wbs_code`，绝不能生成 `children`。每条
记录的字段名必须逐字使用写入工具 schema 中的英文技术字段，禁止中文字段名和 schema
外字段。写入成功就是完成边界，无需再调用 `TeamSay`。

`wbs_code` 和其他字段只写本次资料明确给出的内容；未识别字段省略，
没有提供前置关系时省略 `predecessor_wbs_codes`，不要写空数组清除原关系。
更新草稿时保留该分区已提取的其他记录，不复制全部正式旧节点，不把附件缺行当作
删除节点。平台负责新旧匹配；资料是否合格、必填要求及关系问题全部由当前核验 MCP
判定，不另设判断。完成本分区即可提交，不等其他分区齐全。

`source_files` 必须非空并明确记录本次使用的全部 `file_id/chunk_id` 与文件名；
`extraction_notes` 只记录来源位置、读取情况和格式转换，不判断序号、层级或时间是否正确，没有说明时
传空数组。证据映射不得只保留在邀请任务中，提交前确认 notes 与最终 payload 一致。

资料是否合格、哪些字段必填、能否留空以及本批次问题范围，全部由当前核验 MCP 决定；智能体和前后端不得另设业务判定，也不得擅自要求质量空白字段补齐。

## 初始化智能体职责边界

只读取用户上传的资料、提取原始内容并形成草稿。资料是否正确、完整、重复、匹配、必填或允许留空，全部交给平台当前绑定的核验 MCP；不得自己核验，不得把自己的判断写进 extraction_notes 或向用户作为核验结论输出。只可原样转述 MCP 的结论。发现问题后由用户人工修改原始资料并重新上传，智能体不得代为修正。
