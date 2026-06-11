# 工程智管家 MVP API 接口规划

> 文档状态：开发前期基线版
> 编制日期：2026-06-09
> 文档目的：规划前后端 API 边界，供后端建路由、前端联调、测试编写用例使用。

---

## 1. 接口设计原则

- 接口按业务模块组织，不按页面硬编码。
- 所有业务数据必须带 project_id 或从当前项目上下文获取。
- 智能生成内容必须有确认接口。
- 文件导入、日报解析、草稿生成、填报助手等耗时动作应返回任务或处理状态。
- 外部平台密码、验证码不通过本系统接口传输和保存。
- 所有关键写操作写入操作日志。

---

## 2. 通用约定

### 2.1 项目 ID 约定

- 对外 API、请求体、响应体统一使用 project_id 表示项目上下文。
- projects.id 是项目唯一主键，也是项目级业务资源的路径参数。
- 项目级资源路径统一使用 `/api/projects/{project_id}/...`。

### 2.2 响应格式建议

```json
{
  "success": true,
  "data": {},
  "message": "ok",
  "request_id": "optional-request-id"
}
```

错误响应：

```json
{
  "success": false,
  "error_code": "VALIDATION_ERROR",
  "message": "字段不能为空",
  "details": {}
}
```

### 2.3 分页参数

| 参数 | 说明 |
|---|---|
| page | 页码，从 1 开始 |
| page_size | 每页数量 |
| keyword | 搜索关键词 |
| status | 状态过滤 |

### 2.4 权限原则

| 操作 | 权限要求 |
|---|---|
| 项目配置 | 系统配置责任或管理员 |
| WBS/风险源导入 | 系统配置责任或管理员 |
| 任务处理 | 任务负责人或确认人 |
| 日报确认 | 日报资料责任或任务负责人 |
| 草稿审核 | 技术审核、风险管控或指定审核人 |
| 网页填报 | 平台填报责任或指定任务负责人 |
| 日志查询 | 管理员、项目负责人或授权人员 |

### 2.5 异步作业约定

文件解析、日报工作流、草稿工作流、网页填报等耗时动作一律走异步：触发接口不同步返回结果，而是返回作业标识，前端轮询查看进度。

- 触发接口返回：`{ "job_id": 123, "status": "queued" }`（作业落 async_jobs 表，由 Celery Worker 执行，celery_task_id 只作为内部执行标识）。
- 轮询作业状态：`GET /api/async-jobs/{job_id}`，返回 status（queued/running/interrupted/succeeded/failed/cancelled）、progress、error_message、target_type、target_id。
- 人在环：status 为 interrupted 表示 LangGraph 工作流在确认点暂停，同时任务中心生成一条确认任务；用户在对应确认接口（如日报确认、草稿确认）提交后，工作流从检查点恢复，不重跑整条流程。
- 取消作业：`POST /api/async-jobs/{job_id}/cancel`。

---

## 3. 项目与成员接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/projects | 查询项目列表 |
| POST | /api/projects | 创建项目 |
| GET | /api/projects/{project_id} | 查询项目详情 |
| PATCH | /api/projects/{project_id} | 更新项目 |
| GET | /api/projects/{project_id}/members | 查询项目成员 |
| POST | /api/projects/{project_id}/members | 添加项目成员 |
| PATCH | /api/project-members/{project_member_id} | 更新项目成员 |
| GET | /api/responsibility-tags | 查询责任标签 |
| PUT | /api/project-members/{project_member_id}/responsibilities | 保存成员责任标签 |

创建项目请求示例：

```json
{
  "project_name": "合流污水一期复线工程",
  "owner_unit": "所属单位",
  "description": "试点项目"
}
```

---

## 4. WBS 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/projects/{project_id}/wbs/import | 上传并导入 WBS 文件 |
| GET | /api/projects/{project_id}/wbs | 查询 WBS 工序列表 |
| GET | /api/wbs/{wbs_item_id} | 查询工序详情 |
| PATCH | /api/wbs/{wbs_item_id} | 调整工序信息 |
| DELETE | /api/wbs/{wbs_item_id} | 删除或停用工序 |
| POST | /api/projects/{project_id}/wbs/preview-import | 预览导入结果 |
| POST | /api/projects/{project_id}/wbs/confirm-import | 确认导入结果 |

WBS 工序响应示例：

```json
{
  "wbs_item_id": 101,
  "project_id": 1,
  "code": "1.2.3",
  "wbs_item_name": "盾构接收",
  "level": 3,
  "planned_start": "2026-06-30",
  "planned_finish": "2026-07-05",
  "status": "not_started"
}
```

---

## 5. 风险源接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/projects/{project_id}/risks/import | 上传并导入风险源清单 |
| GET | /api/projects/{project_id}/risks | 查询风险源列表 |
| GET | /api/risks/{risk_source_id} | 查询风险源详情 |
| PATCH | /api/risks/{risk_source_id} | 更新风险源 |
| DELETE | /api/risks/{risk_source_id} | 删除或停用风险源 |
| POST | /api/projects/{project_id}/risks/preview-import | 预览导入结果 |
| POST | /api/projects/{project_id}/risks/confirm-import | 确认导入结果 |

风险源响应示例：

```json
{
  "risk_source_id": 201,
  "project_id": 1,
  "risk_name": "盾构接收风险",
  "level": "重大风险",
  "type": "盾构施工",
  "planned_start": "2026-06-20",
  "planned_finish": "2026-07-10",
  "responsible_user_id": 5,
  "control_requirements": "接收前完成专项检查和监测资料确认"
}
```

---

## 6. WBS-风险关联接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/projects/{project_id}/wbs-risk-links | 查询关联列表 |
| POST | /api/projects/{project_id}/wbs-risk-links | 创建关联 |
| GET | /api/wbs-risk-links/{link_id} | 查询关联详情 |
| PATCH | /api/wbs-risk-links/{link_id} | 更新关联 |
| DELETE | /api/wbs-risk-links/{link_id} | 停用关联 |
| POST | /api/projects/{project_id}/wbs-risk-links/recommend | 自动推荐关联，P1 |

创建关联请求示例：

```json
{
  "wbs_item_id": 101,
  "risk_source_id": 201,
  "trigger_stage": "before_start",
  "reminder_days": [14, 7, 3],
  "responsible_user_id": 5,
  "confirmer_user_id": 2,
  "basis": "盾构接收工序对应盾构接收风险"
}
```

---

## 7. 任务中心接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/tasks/my | 查询我的任务 |
| GET | /api/projects/{project_id}/tasks | 查询项目任务 |
| GET | /api/tasks/summary | 查询任务统计 |
| GET | /api/tasks/{task_id} | 查询任务详情 |
| PATCH | /api/tasks/{task_id}/status | 更新任务状态 |
| GET | /api/tasks/{task_id}/status-history | 查询任务状态流转历史 |
| GET | /api/tasks/{task_id}/dependencies | 查询任务依赖关系 |
| POST | /api/tasks/{task_id}/dependencies | 创建任务依赖关系 |
| POST | /api/tasks/{task_id}/materials | 提交材料 |
| POST | /api/tasks/{task_id}/comments | 添加任务备注 |
| POST | /api/tasks/{task_id}/confirm | 确认任务结果 |
| POST | /api/projects/{project_id}/tasks/generate-risk-reminders | 手动触发风险提醒生成 |

任务详情响应示例：

```json
{
  "task_id": 301,
  "title": "盾构接收风险预警",
  "type": "risk_warning",
  "status": "pending",
  "assignee_user_id": 5,
  "confirmer_user_id": 2,
  "due_at": "2026-06-23T18:00:00+08:00",
  "risk_source_id": 201,
  "wbs_item_id": 101,
  "trigger_reason": "盾构接收工序计划于2026-06-30开始，按重大风险提前7天提醒",
  "required_materials": ["现场照片", "监测日报", "风险控制措施"]
}
```

### 7.1 自然语言录入预留入口

自然语言录入作为 B 类第三条智能工作流保留接口形态，本期只在契约和数据模型中占位，不纳入 MVP 必交付实现。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/projects/{project_id}/nl-intake | 自然语言录入预留入口，后续触发 nl_intake 异步作业并生成待确认任务/草稿 |

---

## 8. 日报目录与解析接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/projects/{project_id}/daily-report-config | 查询日报目录配置 |
| PUT | /api/projects/{project_id}/daily-report-config | 保存日报目录配置 |
| POST | /api/projects/{project_id}/daily-reports/scan | 手动扫描日报目录 |
| GET | /api/projects/{project_id}/daily-reports/files | 查询日报文件列表 |
| GET | /api/daily-report-files/{file_id} | 查询日报文件详情 |
| POST | /api/daily-report-files/{file_id}/parse | 手动触发解析 |
| GET | /api/daily-reports/{parse_result_id} | 查询解析结果 |
| PATCH | /api/daily-reports/{parse_result_id} | 人工修正解析结果 |
| POST | /api/daily-reports/{parse_result_id}/confirm | 确认解析结果 |

日报确认请求示例：

```json
{
  "report_date": "2026-06-09",
  "construction_content": "接收井现场准备，完成测量复核和材料进场检查",
  "progress_items": [
    {
      "wbs_item_id": 101,
      "progress_text": "盾构接收准备工作进行中",
      "match_status": "confirmed"
    }
  ]
}
```

---

## 9. 风险草稿接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/risks/{risk_source_id}/drafts | 生成风险上报草稿 |
| GET | /api/risks/{risk_source_id}/drafts | 查询风险草稿列表 |
| GET | /api/risk-drafts/{draft_id} | 查询草稿详情 |
| PATCH | /api/risk-drafts/{draft_id} | 修改草稿 |
| POST | /api/risk-drafts/{draft_id}/submit-review | 提交审核 |
| POST | /api/risk-drafts/{draft_id}/confirm | 确认草稿 |
| POST | /api/risk-drafts/{draft_id}/cancel | 取消草稿 |
| POST | /api/risk-drafts/{draft_id}/fill-package | 生成平台填报包 |

生成草稿请求示例：

```json
{
  "wbs_item_id": 101,
  "daily_report_parse_result_ids": [401, 402],
  "attachment_ids": [501, 502],
  "extra_note": "请结合最新监测日报生成风险进展说明"
}
```

---

## 10. 填报包与网页填报助手接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/fill-packages/{package_id} | 查询填报包详情 |
| GET | /api/fill-packages/{package_id}/preview | 预览待填字段和附件 |
| POST | /api/fill-packages/{package_id}/start | 启动填报助手 |
| GET | /api/fill-packages/{package_id}/progress | 查询填报进度 |
| POST | /api/fill-packages/{package_id}/mark-saved | 标记平台草稿已保存 |
| POST | /api/fill-packages/{package_id}/mark-submitted-by-user | 标记用户已最终提交 |
| POST | /api/fill-packages/{package_id}/cancel | 取消填报任务 |

填报包预览响应示例：

```json
{
  "package_id": 601,
  "target_platform": "公司平台",
  "business_flow": "风险进展上报",
  "fields": [
    {
      "label": "风险名称",
      "value": "盾构接收风险",
      "required": true,
      "mapping_status": "mapped"
    }
  ],
  "attachments": [
    {
      "filename": "现场照片1.jpg",
      "file_type": "image"
    }
  ]
}
```

---

## 11. 附件接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/projects/{project_id}/attachments | 上传附件 |
| GET | /api/projects/{project_id}/attachments | 查询附件列表 |
| GET | /api/attachments/{attachment_id} | 查询附件详情 |
| DELETE | /api/attachments/{attachment_id} | 删除附件 |

---

## 12. 日志接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/operation-logs | 查询操作日志 |
| GET | /api/projects/{project_id}/operation-logs | 查询项目日志 |
| GET | /api/tasks/{task_id}/operation-logs | 查询任务日志 |
| GET | /api/risks/{risk_source_id}/operation-logs | 查询风险源日志 |

---

## 13. 待确认接口问题

- 已定：草稿生成、日报解析、网页填报等耗时动作一律走异步作业 + 轮询（见 2.5）。
- 已定：网页填报助手由后端 Playwright 受控服务启动，用户自行登录，不自动提交。
- 待确认：文件上传接口的统一设计（大小限制、分片、存储路径）。
- 待确认：导入预览是否必须支持字段映射调整。
- 待确认：操作日志是否需要按租户或项目隔离。
- 待确认：自然语言录入预留入口的首期启用范围与确认页面形态。
