import type { Component } from 'vue'

import type { RiskLevel, Task, TaskStatus } from '@/types'

export type ChatMessage = {
  id: string
  role: 'assistant' | 'user'
  content: string
  generatedTaskIds?: string[]
  attachments?: ChatAttachment[]
}

export type ChatAttachment = {
  id: string
  name: string
  size: number
  type: string
}

export type TaskNodeType = 'manual' | 'project_chat_message'
export type TaskMessageMentionMode = 'none' | 'all' | 'users'
export type TaskFlowStepDraft = {
  id: string
  name: string
  node_type: TaskNodeType
  owner_user_id: string
  due_at: string
  material: string
  target_channel_id: number | null
  mention_mode: TaskMessageMentionMode
  mentioned_user_ids: number[]
  message_content: string
}
export type TriggerIntervalUnit = 'minute' | 'hour' | 'day' | 'week' | 'month'
export type TaskRunMode = 'immediate' | 'once' | 'recurring' | 'calendar'
export type TriggerEndMode = 'never' | 'until' | 'count'
export type TriggerCalendarMode = 'daily' | 'weekdays' | 'weekly' | 'monthly'
export type TaskSchedule = {
  id: string
  flow_id: string
  title: string
  status: string
  active: boolean
  paused: boolean
  trigger_description: string
  next_fire_at: string | null
  last_fire_at: string | null
  fire_count: number
  last_error: string
  execution_kind: 'responsibility' | 'automation'
  action?: { type?: string; mention_mode?: string; content?: string } | null
}
export type GeneratedTaskFlow = {
  title: string
  task_type: Task['type']
  risk_level: RiskLevel
  assignee_user_id?: number | null
  confirmer_user_id?: number | null
  wbs_item_id?: number | null
  risk_source_id?: number | null
  run_mode: 'single' | 'scheduled' | TaskRunMode
  trigger_date: string
  trigger_time: string
  trigger_rule: string
  trigger_interval_value: number
  trigger_interval_unit: TriggerIntervalUnit
  cc: string
  steps: Array<{
    name: string
    node_type?: TaskNodeType
    owner_user_id?: number | null
    due_at?: string | null
    material?: string
    action?: {
      type: 'project_chat_message'
      channel_id: number
      sender_agent_id: string
      sender_agent_name?: string
      mention_mode: TaskMessageMentionMode
      mentioned_user_ids: number[]
      content: string
    }
  }>
  generated_by: 'ai'
  generation_note: string
}

export type WorkQueueStatus = 'unfinished' | 'done'
export type WorkQueueCategory = 'decision' | 'upload' | 'generated'
export type WorkQueueTone = 'danger' | 'upload' | 'warning' | 'info' | 'success'
export type HomeWorkItem = {
  id: string
  rank: number
  workflowStatus: WorkQueueStatus
  category: WorkQueueCategory
  label: string
  title: string
  reason: string
  tags: string[]
  owner: string
  role: string
  deadline: string
  action: string
  to: string
  tone: WorkQueueTone
  icon: Component
}

export function workQueueStatus(task: Task): WorkQueueStatus {
  return task.status === 'done' ? 'done' : 'unfinished'
}

export function isUserWorkQueueTask(task: Task, userId: string) {
  if (!userId || task.status === 'cancelled') return false
  if (task.status === 'done') {
    return task.responsibleId === userId
      || task.confirmatorId === userId
      || task.workflowSteps.some(step => step.owner_user_id === userId && step.status === 'completed')
  }
  const currentStep = task.workflowSteps.find(step => step.status !== 'completed')
  return task.responsibleId === userId
    || currentStep?.owner_user_id === userId
    || (task.status === 'waiting_confirm' && task.confirmatorId === userId)
}

export function workQueueCategory(task: Task): WorkQueueCategory {
  if (task.status === 'need_more_info' || task.type === 'material_missing') return 'upload'
  if (task.status === 'processing' || task.type === 'fill_platform') return 'generated'
  return 'decision'
}

export function workQueueLabel(task: Task) {
  if (task.status === 'done') return '已完成'
  if (task.status === 'cancelled') return '已取消'
  if (task.status === 'overdue') return '已逾期'
  return '待处理'
}

export function workQueueDeadline(value: string) {
  if (!value) return '未设置截止时间'
  if (!value.includes(':')) return `截止 ${formatDateTime(value, 'end')}`
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp)) return `截止 ${value.replace('T', ' ')}`
  const date = new Date(timestamp)
  const pad = (part: number) => String(part).padStart(2, '0')
  return `截止 ${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

export function formatFileSize(bytes: number) {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function projectBaseInfoRow(label: string, rawValue?: string | null) {
  const value = String(rawValue || '').trim()
  return { label, value: value || '未填写', present: Boolean(value) }
}

export function projectDateLabel(value?: string | null) {
  if (!value) return ''
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp)) return value
  const date = new Date(timestamp)
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export function projectDocumentTypeLabel(fileType: string, fileName: string) {
  const extension = fileName.includes('.') ? fileName.split('.').pop() || '' : ''
  const normalized = (fileType || extension).trim().replace(/^\./, '').split('/').pop() || ''
  return normalized ? normalized.toUpperCase() : '文件'
}

export function projectDocumentFileSizeLabel(fileSize: number) {
  return fileSize > 0 ? formatFileSize(fileSize) : '大小未记录'
}

export function projectDocumentFolderLabel(folderPath: string) {
  const segments = folderPath.replace(/\\/g, '/').split('/').map(item => item.trim()).filter(Boolean)
  return segments.length ? segments[segments.length - 1] : '资料库根目录'
}

export function projectDateRange(start?: string | null, end?: string | null) {
  const startLabel = projectDateLabel(start)
  const endLabel = projectDateLabel(end)
  if (startLabel && endLabel) return `${startLabel} 至 ${endLabel}`
  if (startLabel) return `${startLabel} 起`
  if (endLabel) return `截至 ${endLabel}`
  return '未填写'
}

export function riskLabel(level: RiskLevel) {
  return ({ critical: '重大', high: '高', medium: '中', low: '低' } as Record<RiskLevel, string>)[level]
}

export function wbsStatusLabel(status: string) {
  return ({ not_started: '未开始', in_progress: '进行中', done: '已完成', delayed: '已延期' } as Record<string, string>)[status] || status
}

export function projectTaskStatusLabel(status: TaskStatus) {
  return ({ pending: '待处理', processing: '进行中', need_more_info: '待补充', waiting_confirm: '待确认', done: '已完成', overdue: '逾期', cancelled: '已取消' } as Record<TaskStatus, string>)[status]
}

export function taskClosureLabel(task: Task) {
  const currentStep = task.workflowSteps.find(step => step.status !== 'completed') ?? task.workflowSteps[task.workflowSteps.length - 1]
  return currentStep?.closure || ({ pending: '未闭环', processing: '未闭环', need_more_info: '待补充', waiting_confirm: '待复核', done: '已闭环', overdue: '待复核', cancelled: '已取消' } as Record<TaskStatus, string>)[task.status]
}

export function taskClosureTone(task: Task) {
  const label = taskClosureLabel(task)
  if (label === '已闭环') return 'closed'
  if (label.includes('复核')) return 'review'
  if (label.includes('补充')) return 'supplement'
  if (label.includes('取消')) return 'cancelled'
  return 'open'
}

export function taskMaterialLabel(task: Task) {
  const currentStep = task.workflowSteps.find(step => step.status !== 'completed')
  const material = currentStep?.material || currentStep?.note || task.workflowSteps[task.workflowSteps.length - 1]?.material
  return material || (task.missingCount > 0 ? `待补齐 ${task.missingCount} 项资料` : '暂无待补充材料')
}

export function taskTypeLabel(type: Task['type']) {
  return ({ risk_alert: '风险预警', material_missing: '资料缺项', daily_confirm: '日报确认', draft_review: '草稿审核', fill_platform: '平台填报', automation: '自动化动作' } as Record<Task['type'], string>)[type]
}

export function taskStepLabel(status: Task['workflowSteps'][number]['status']) {
  return ({ pending: '待处理', processing: '处理中', completed: '已完成', blocked: '受阻' } as Record<Task['workflowSteps'][number]['status'], string>)[status]
}

export function taskSourceLabel(type: Task['type']) {
  return ({ risk_alert: 'WBS 风险规则自动触发', material_missing: '风险草稿资料校验', daily_confirm: '日报目录解析', draft_review: '风险草稿生成', fill_platform: '填报包生成', automation: '任务引擎自动执行' } as Record<Task['type'], string>)[type]
}

export function taskProgress(status: TaskStatus) {
  return ({ overdue: 20, pending: 30, processing: 58, need_more_info: 45, waiting_confirm: 78, done: 100, cancelled: 0 } as Record<TaskStatus, number>)[status]
}

export function formatDateTime(date: string, mode: 'start' | 'end' = 'start') {
  if (!date) return '—'
  const normalized = /^\d{4}-\d{2}-\d{2}$/.test(date)
    ? `${date}T${mode === 'end' ? '18:00' : '00:00'}:00`
    : date
  const timestamp = Date.parse(normalized)
  if (!Number.isFinite(timestamp)) return date.replace('T', ' ')
  const value = new Date(timestamp)
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())} ${pad(value.getHours())}:${pad(value.getMinutes())}`
}

export function formatScheduleDateTime(value: string) {
  return formatDateTime(value)
}

export function statusLabel(status: TaskStatus | string) {
  return ({ pending: '待处理', processing: '处理中', need_more_info: '待补充资料', waiting_confirm: '待确认', done: '已完成', overdue: '已逾期', cancelled: '已取消', running: '处理中', review: '待确认', blocked: '受阻', pending_confirm: '待确认', confirmed: '已确认' } as Record<string, string>)[status] ?? status
}

export function nowStr() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`
}
