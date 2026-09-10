import dayjs from 'dayjs'
import { displayWbsItemType, displayWbsPriorityText, displayWbsStatusText } from '@/utils/initializationFieldPresentation'
export { displayWbsItemType, displayWbsPriorityText, displayWbsStatusText, formatInitializationDate } from '@/utils/initializationFieldPresentation'

import type { RiskLevel, RiskSource, WbsItem } from '@/types'
import {
  runtimeTraceFromExtraData,
  type AgentRuntimeTrace,
  type ApiAgentMessage,
} from '@/types/agentRuntime'
import type {
  ApiInitializationDraft,
  InitializationAttachment,
  InitializationDraftIssue,
  InitializationDraftWbs,
  InitializationWbsTreeRow,
  ManualWbsTreeRow,
  MaterialAgentMessage,
} from './types'


export const ACTIVE_MATERIAL_AGENT_STATUSES = new Set([
  'creating',
  'running',
  'interrupting',
  'awaiting_permission',
  'awaiting_external_result',
])

const ACTIVE_COLLABORATION_WORK_STATUSES = new Set([
  'idle',
  'queued',
  'running',
  'waiting',
])

export const initializationVisibleIssueFields: Record<
  InitializationDraftIssue['section'],
  Set<string> | null
> = {
  project: null,
  personnel: new Set([
    'serial_no',
    'real_name',
    'identity_card_no',
    'position_name',
    'certificate_no',
    'responsibility_description',
  ]),
  wbs: new Set([
    'wbs_code',
    'name',
    'level',
    'planned_start_at',
    'planned_finish_at',
    'progress_percent',
    'status_text',
    'priority_text',
    'predecessor_wbs_codes',
    'parent_wbs_code',
  ]),
  risks: new Set([
    'serial_no',
    'related_process_name',
    'risk_part',
    'risk_level',
    'evaluation_condition',
    'risk_window_start_date',
    'risk_window_end_date',
    'summary',
  ]),
  quality_requirements: new Set([
    'wbs_code',
    'quality_acceptance_item',
    'control_indicator',
    'inspection_frequency',
    'related_documents',
  ]),
}

export const projectFieldLabels: Record<string, string> = {
  serial_no: '序号',
  real_name: '姓名',
  identity_card_no: '身份证号',
  position_name: '岗位',
  certificate_no: '证书编号',
  responsibility_description: '岗位职责',
  wbs_code: 'WBS 编码',
  parent_wbs_code: '上级 WBS',
  predecessor_wbs_codes: '前置 WBS',
  level: '层级',
  name: '工序名称',
  planned_start_at: '计划开始',
  planned_finish_at: '计划完成',
  progress_percent: '进度',
  status_text: '状态',
  priority_text: '优先级',
  related_process_name: '相关工序',
  risk_part: '风险部位',
  risk_level: '风险等级',
  evaluation_condition: '风险评价条件',
  risk_window_start_date: '风险窗口开始',
  risk_window_end_date: '风险窗口结束',
  summary: '摘要',
  quality_acceptance_item: '质量验收项目',
  control_indicator: '控制指标',
  inspection_frequency: '检查频次',
  related_documents: '相关资料',
  engineering_type_description: '工程类型说明',
  contract_start_date: '合同开工',
  contract_end_date: '合同竣工',
  contract_duration_days: '合同工期',
  contract_amount_wan_yuan: '合同金额',
  construction_unit_name: '建设单位',
  general_contractor_unit_name: '总承包单位',
  supervision_unit_name: '监理单位',
  design_unit_name: '设计单位',
  survey_unit_name: '勘察单位',
}

export function buildManualWbsTree(items: WbsItem[]) {
  const itemIds = new Set(items.map(item => item.id))
  const children = new Map<string, WbsItem[]>()
  const roots: WbsItem[] = []
  const collator = new Intl.Collator('zh-CN', {
    numeric: true,
    sensitivity: 'base',
  })
  const compare = (left: WbsItem, right: WbsItem) => (
    (left.sortOrder || 0) - (right.sortOrder || 0)
    || collator.compare(left.code, right.code)
  )
  for (const item of items) {
    if (item.parentId && itemIds.has(item.parentId)) {
      children.set(item.parentId, [...(children.get(item.parentId) || []), item])
    } else {
      roots.push(item)
    }
  }
  roots.sort(compare)
  for (const rows of children.values()) rows.sort(compare)

  const result: ManualWbsTreeRow[] = []
  const visited = new Set<string>()
  const walk = (item: WbsItem, depth: number) => {
    if (visited.has(item.id)) return
    visited.add(item.id)
    const descendants = children.get(item.id) || []
    result.push({ item, depth, hasChildren: descendants.length > 0 })
    descendants.forEach(child => walk(child, depth + 1))
  }
  roots.forEach(item => walk(item, 0))
  items
    .filter(item => !visited.has(item.id))
    .sort(compare)
    .forEach(item => walk(item, 0))
  return { rows: result, children }
}

export function buildInitializationWbsTree(items: InitializationDraftWbs[]) {
  const itemByCode = new Map(items.map(item => [item.wbs_code, item]))
  const childrenByParent = new Map<string, InitializationDraftWbs[]>()
  const roots: InitializationDraftWbs[] = []
  const compare = (
    left: InitializationDraftWbs,
    right: InitializationDraftWbs,
  ) => left.wbs_code.localeCompare(right.wbs_code, 'zh-CN', {
    numeric: true,
    sensitivity: 'base',
  })

  for (const item of items) {
    const parentCode = item.parent_wbs_code || ''
    if (parentCode && itemByCode.has(parentCode)) {
      const siblings = childrenByParent.get(parentCode) || []
      siblings.push(item)
      childrenByParent.set(parentCode, siblings)
    } else {
      roots.push(item)
    }
  }
  roots.sort(compare)
  for (const siblings of childrenByParent.values()) siblings.sort(compare)

  const rows: InitializationWbsTreeRow[] = []
  const visited = new Set<string>()
  const append = (
    item: InitializationDraftWbs,
    depth: number,
    ancestorCodes: string[],
  ) => {
    if (visited.has(item.wbs_code)) return
    visited.add(item.wbs_code)
    const children = childrenByParent.get(item.wbs_code) || []
    rows.push({
      item,
      depth,
      ancestorCodes,
      hasChildren: children.length > 0,
    })
    for (const child of children) {
      append(child, depth + 1, [...ancestorCodes, item.wbs_code])
    }
  }
  for (const root of roots) append(root, 0, [])
  for (const item of items) {
    if (!visited.has(item.wbs_code)) append(item, 0, [])
  }
  return { rows, groupCodes: [...childrenByParent.keys()] }
}

export function materialAgentTraceHasActiveRuntime(trace: AgentRuntimeTrace) {
  if (!ACTIVE_MATERIAL_AGENT_STATUSES.has(trace.status)) return false
  const hasActivePlan = (trace.tasksContext?.tasks || []).some(
    task => task.state === 'pending' || task.state === 'in_progress',
  )
  const hasActiveCollaboration = trace.collaborations.some((member) => {
    const status = member.work_status === 'reported'
      ? 'completed'
      : (
          ['idle', 'queued'].includes(member.work_status)
          && member.current_activity?.state === 'running'
            ? 'running'
            : member.work_status
        )
    return ACTIVE_COLLABORATION_WORK_STATUSES.has(status)
  })
  return hasActivePlan || hasActiveCollaboration
}

export function cloneMaterialAgentTrace(
  trace: AgentRuntimeTrace,
): AgentRuntimeTrace {
  return JSON.parse(JSON.stringify(trace)) as AgentRuntimeTrace
}

export function traceHasPendingMaterialToolCall(
  trace: AgentRuntimeTrace | null | undefined,
  replyId: string,
  toolCallId: string,
) {
  if (!trace || !ACTIVE_MATERIAL_AGENT_STATUSES.has(trace.status)) return false
  const messageCall = trace.messages.some(runtimeMessage => (
    runtimeMessage.id === replyId
    && !runtimeMessage.finished_at
    && runtimeMessage.content.some(block => (
      block.type === 'tool_call'
      && block.id === toolCallId
      && block.state === 'asking'
    ))
  ))
  if (messageCall) return true
  return trace.subagentHitl.some(entry => (
    entry.reply_id === replyId
    && (entry.event.tool_calls || []).some(call => (
      call.id === toolCallId && call.state === 'asking'
    ))
  ))
}

export function attachmentsFromMessage(
  item: ApiAgentMessage,
): InitializationAttachment[] {
  const raw = item.extra_data?.initialization_files
  if (!Array.isArray(raw)) return []
  return raw.flatMap((value) => {
    if (!value || typeof value !== 'object') return []
    const file = value as Record<string, unknown>
    const id = Number(file.id)
    const name = String(file.name || '')
    const size = Number(file.size) || 0
    return Number.isFinite(id) && name
      ? [{ id: String(id), name, size }]
      : []
  })
}

export function mapMaterialAgentMessage(
  item: ApiAgentMessage,
): MaterialAgentMessage {
  const attachments = attachmentsFromMessage(item)
  return {
    id: String(item.id),
    role: item.role,
    content: item.content,
    attachments: attachments.length ? attachments : undefined,
    runtimeTrace: runtimeTraceFromExtraData(item.extra_data),
  }
}

export function maskedIdentityCard(value: string) {
  if (!value) return '未登记身份证号'
  if (value.length <= 8) return `${value.slice(0, 2)}****`
  return `${value.slice(0, 3)} **** **** ${value.slice(-4)}`
}

export function formatFormalDate(value?: string) {
  return value ? value.slice(0, 10) : ''
}

export function formatSourceDateTime(value?: string) {
  if (!value) return ''
  const date = dayjs(value)
  return date.isValid() ? date.format('YYYY-MM-DD HH:mm') : value
}

export function formatWbsDuration(value?: number) {
  if (value == null || Number.isNaN(value)) return '未计算工期'
  return `${Number.isInteger(value) ? value : value.toFixed(1)} 小时`
}

export function formatProgress(value: number) {
  return Number.isInteger(value) ? value : value.toFixed(1)
}

export function formatRiskWindow(item: RiskSource) {
  const start = formatFormalDate(item.controlStart)
  const end = formatFormalDate(item.controlEnd)
  if (start && end) return `${start} 至 ${end}`
  return start || end || '未设置风险窗口'
}

export function wbsStatusLabel(status: WbsItem['status']) {
  return ({
    not_started: '未开始',
    in_progress: '进行中',
    done: '已完成',
    delayed: '已延期',
  } as Record<WbsItem['status'], string>)[status]
}

export function formalWbsStatusLabel(item: WbsItem) {
  return displayWbsStatusText(item.statusText)
}

export function formalWbsPriorityLabel(value?: string) {
  return displayWbsPriorityText(value, '')
}

export function formalWbsItemType(item: WbsItem) {
  return displayWbsItemType(item.itemType)
}

export function riskLabel(level: RiskLevel) {
  return ({
    critical: '重大风险',
    high: '高风险',
    medium: '中风险',
    low: '低风险',
  } as Record<RiskLevel, string>)[level]
}

export function formalRiskLevelLabel(item: RiskSource) {
  const raw = item.levelText?.trim() || ''
  const translated: Record<string, string> = {
    critical: '重大风险',
    high: '高风险',
    medium: '中风险',
    low: '低风险',
  }
  return translated[raw.toLowerCase()] || raw || riskLabel(item.level)
}

export function initializationDraftStatusLabel(
  status: ApiInitializationDraft['status'],
) {
  return {
    collecting: '资料持续整理中',
    reviewing: '平台核验中',
    invalid: '部分内容需要修正',
    ready: '草稿可分批确认',
    applied: '本次资料已提交',
    rejected: '草稿已退回',
  }[status]
}

export function initializationSectionLabels(sections: string[]) {
  const labels: Record<string, string> = {
    project: '工程信息',
    personnel: '人员与岗位',
    wbs: 'WBS 与进度',
    risks: '风险源',
    quality_requirements: '质量指标',
  }
  return sections.map(section => labels[section] || section).join('、')
}

export function initializationDraftStageHint(draft: ApiInitializationDraft) {
  if (draft.status === 'applied') return '已写入项目'
  if (draft.status === 'collecting') return '专家处理中'
  if (draft.status === 'reviewing') return '规则核验中'
  return '可选择内容确认'
}

export function initializationDraftCollapsedLabel(
  draft: ApiInitializationDraft,
) {
  if (draft.status === 'applied') return '初始化草稿已写入项目'
  if (draft.status === 'collecting') return '初始化草稿正在整理'
  if (draft.status === 'reviewing') return '初始化草稿等待核验'
  return '有待确认草稿'
}

export function formatValidationDuration(durationMs?: number | null) {
  if (durationMs === null || durationMs === undefined) return '耗时未知'
  if (durationMs < 1000) return `${durationMs} 毫秒`
  return `${(durationMs / 1000).toFixed(durationMs < 10_000 ? 1 : 0)} 秒`
}

export function formatInitializationProgress(
  value?: number | string | null,
) {
  if (value === null || value === undefined || value === '') return ''
  const progress = Number(value)
  return Number.isFinite(progress) ? `${progress}%` : String(value)
}

export { generateInitializationPassword } from '@/utils/initializationChangePresentation'

export function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function sourceFieldLabel(value: string) {
  return ({
    draft_title: '草稿标题',
    draft_content: '草稿内容',
    source_refs: '来源资料',
  } as Record<string, string>)[value] || value
}

export function formatTime(value: string) {
  return value
    ? new Date(value).toLocaleString('zh-CN', { hour12: false })
    : '刚刚'
}
