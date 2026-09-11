import type { InitializationChange, InitializationChangeCredential, InitializationOperation, InitializationRequiredCredential, InitializationSection } from '@/types/initializationChanges'
import { displayWbsItemType, displayWbsPriorityText, displayWbsStatusText, formatInitializationDate, formatInitializationDateTime } from './initializationFieldPresentation'

export const initializationSections: Array<{ key: InitializationSection; label: string }> = [
  { key: 'project', label: '工程信息' }, { key: 'personnel', label: '人员与岗位' },
  { key: 'wbs', label: 'WBS 与进度' }, { key: 'risks', label: '风险源' }, { key: 'quality_requirements', label: '质量指标' },
]
export const initializationOperationLabels: Record<InitializationOperation, string> = {
  add: '新增', update: '更新', unchanged: '无变化', conflict: '待核对', applied: '已提交',
}
export type InitializationChangeFilter = 'all' | 'add' | 'update'
export const initializationChangeFilters: Array<{ key: InitializationChangeFilter; label: string }> = [
  { key: 'all', label: '全部' }, { key: 'add', label: '新增' }, { key: 'update', label: '更新' },
]
const fieldLabels: Record<string, string> = {
  name: '名称', engineering_type_description: '工程概况', contract_start_date: '合同开始日期',
  contract_end_date: '合同结束日期', contract_duration_days: '合同工期（天）', contract_amount_wan_yuan: '合同金额（万元）',
  construction_unit_name: '建设单位', general_contractor_unit_name: '总承包单位', supervision_unit_name: '监理单位',
  design_unit_name: '设计单位', survey_unit_name: '勘察单位', real_name: '姓名', identity_card_no: '身份证号',
  position_name: '岗位', certificate_no: '证书编号', responsibility_description: '职责描述', serial_no: '序号',
  wbs_code: 'WBS 编码', parent_wbs_code: '上级 WBS', predecessor_wbs_codes: '前置工序', planned_start_at: '计划开始时间',
  planned_finish_at: '计划结束时间', progress_percent: '完成进度（%）', status_text: '状态', priority_text: '优先级',
  duration_hours: '工期（小时）', level: '层级', item_type: '节点类型', sort_order: '排序',
  color_value: '节点颜色', assigned_to_text: '负责人', deadline_at: '截止时间',
  estimated_hours: '预计工时（小时）', time_log_minutes: '已记录工时（分钟）', description: '任务说明',
  budget: '预算', actual_cost: '实际成本', msp_uid: '来源任务唯一编号', msp_id: '来源任务序号',
  source_created_at: '来源创建时间', source_creator: '来源创建人', source_project_path: '来源项目路径', related_process_name: '关联工序',
  risk_part: '风险部位', risk_level: '风险等级', evaluation_condition: '判定条件', risk_window_start_date: '风险开始日期',
  risk_window_end_date: '风险结束日期', summary: '补充说明', quality_acceptance_item: '质量验收项目',
  control_indicator: '控制指标', inspection_frequency: '检查频率', related_documents: '关联资料',
}
export function initializationFieldLabel(name: string) { return fieldLabels[name] || name }
function projectChangeField(change: InitializationChange) {
  if (change.section !== 'project') return null
  const name = change.key.slice(change.key.lastIndexOf(':') + 1)
  return Object.prototype.hasOwnProperty.call(change.after, name) ? name : null
}
export function initializationChangeTitle(change: InitializationChange) {
  const field = projectChangeField(change)
  if (field) return field === 'name' ? '项目名称' : initializationFieldLabel(field)
  if (change.section === 'quality_requirements' && change.after.quality_acceptance_item) {
    return [change.after.wbs_code, change.after.quality_acceptance_item].filter(Boolean).join(' · ')
  }
  return change.title
}
export function formatInitializationChangeValue(value: unknown, fieldName?: string): string {
  if (value === null || value === undefined || value === '') return '未填写'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (Array.isArray(value)) return value.length ? value.map(item => formatInitializationChangeValue(item)).join('、') : '未填写'
  if (typeof value === 'object') return JSON.stringify(value)
  if (fieldName === 'status_text') return displayWbsStatusText(String(value))
  if (fieldName === 'priority_text') return displayWbsPriorityText(String(value))
  if (fieldName === 'item_type') return displayWbsItemType(String(value))
  if (fieldName?.endsWith('_date')) return formatInitializationDate(String(value))
  if (fieldName?.endsWith('_at')) return formatInitializationDateTime(String(value))
  return String(value)
}
export function selectableInitializationChange(change: InitializationChange) {
  return change.operation === 'add' || change.operation === 'update' || change.operation === 'conflict'
}
export function filterInitializationChanges(changes: InitializationChange[], section: InitializationSection | 'all', filter: InitializationChangeFilter, query: string) {
  const search = query.trim().toLocaleLowerCase('zh-CN')
  return changes.filter(change => (
    (section === 'all' || change.section === section)
    && (filter === 'all' || change.operation === filter)
    && (!search || `${initializationChangeTitle(change)} ${initializationComparisonFields(change).map(field => formatInitializationChangeValue(field.after, field.name)).join(' ')}`.toLocaleLowerCase('zh-CN').includes(search))
  ))
}
export function initializationComparisonFields(change: InitializationChange) {
  const changed = new Set(change.fields.map(field => field.name))
  const projectField = projectChangeField(change)
  const names = (projectField ? [projectField] : [...new Set([...Object.keys(change.after), ...Object.keys(change.before || {}), ...changed])])
    .filter(name => !['id', 'record_id', 'project_id'].includes(name))
  return names.map(name => {
    const field = change.fields.find(item => item.name === name)
    return { name, label: initializationFieldLabel(name), before: field ? field.before : change.before?.[name], after: field ? field.after : change.after[name], changed: changed.has(name) }
  }).filter(field => field.changed || hasInitializationValue(field.before) || hasInitializationValue(field.after))
    .sort((a, b) => Number(b.changed) - Number(a.changed))
}
function hasInitializationValue(value: unknown): boolean {
  if (value === null || value === undefined) return false
  if (typeof value === 'string') return value.trim().length > 0
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'object') return Object.keys(value).length > 0
  return true
}
export function reconcileInitializationCredentials(required: InitializationRequiredCredential[], current: InitializationChangeCredential[], password: () => string) {
  const existing = new Map(current.map(item => [item.identity_card_no, item]))
  return required.map(item => ({ ...item, username: existing.get(item.identity_card_no)?.username ?? item.suggested_username, initial_password: existing.get(item.identity_card_no)?.initial_password ?? password() }))
}
export function initializationCredentialError(item: InitializationChangeCredential, all: InitializationChangeCredential[]): string {
  if (!item.username.trim()) return '请输入账号。'
  if (all.filter(other => other.username.trim().toLowerCase() === item.username.trim().toLowerCase()).length > 1) return '账号重复，请为不同人员设置不同账号。'
  if (item.initial_password.length < 8 || item.initial_password.length > 12) return '初始密码须为 8–12 位。'
  return ''
}

export function generateInitializationPassword(length = 12) {
  const targetLength = Math.min(12, Math.max(8, length))
  const groups = ['ABCDEFGHJKLMNPQRSTUVWXYZ', 'abcdefghijkmnopqrstuvwxyz', '23456789', '!@#$%&*']
  const randomIndex = (size: number) => { const value = new Uint32Array(1); globalThis.crypto.getRandomValues(value); return value[0] % size }
  const password = groups.map(group => group[randomIndex(group.length)])
  const all = groups.join('')
  while (password.length < targetLength) password.push(all[randomIndex(all.length)])
  for (let index = password.length - 1; index > 0; index -= 1) {
    const other = randomIndex(index + 1)
    ;[password[index], password[other]] = [password[other], password[index]]
  }
  return password.join('')
}
