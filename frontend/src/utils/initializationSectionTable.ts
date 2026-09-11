import type { InitializationChange, InitializationChangeIssue, InitializationChangePreview, InitializationSection } from '@/types/initializationChanges'
import { initializationComparisonFields, initializationFieldLabel } from './initializationChangePresentation'
import { visibleInitializationChangeTreeRows, type InitializationChangeTreeRow } from './initializationChangeTree'

export type InitializationComparisonField = ReturnType<typeof initializationComparisonFields>[number]
export type InitializationTableColumn = { key: string; label: string; fields: string[] }
const columns: Record<Exclude<InitializationSection, 'project'>, InitializationTableColumn[]> = {
  personnel: [
    { key: 'identity', label: '姓名 / 岗位', fields: ['real_name', 'position_name'] },
    { key: 'certificate', label: '身份证 / 证书', fields: ['identity_card_no', 'certificate_no'] },
    { key: 'responsibility', label: '职责', fields: ['responsibility_description'] },
  ],
  wbs: [
    { key: 'identity', label: '计划层级 / 工序名称', fields: ['wbs_code', 'name', 'item_type'] },
    { key: 'schedule', label: '计划区间', fields: ['planned_start_at', 'planned_finish_at'] },
    { key: 'duration', label: '工期与负责人', fields: ['duration_hours', 'assigned_to_text'] },
    { key: 'progress', label: '完成进度', fields: ['progress_percent'] },
    { key: 'status', label: '状态与优先级', fields: ['status_text', 'priority_text'] },
    { key: 'dependencies', label: '前置 / 上级工序', fields: ['predecessor_wbs_codes', 'parent_wbs_code'] },
  ],
  risks: [
    { key: 'identity', label: '风险部位 / 关联工序', fields: ['risk_part', 'related_process_name'] },
    { key: 'level', label: '风险等级', fields: ['risk_level'] },
    { key: 'window', label: '风险时段', fields: ['risk_window_start_date', 'risk_window_end_date'] },
    { key: 'evaluation', label: '判定条件', fields: ['evaluation_condition'] },
  ],
  quality_requirements: [
    { key: 'identity', label: 'WBS / 验收项目', fields: ['wbs_code', 'quality_acceptance_item'] },
    { key: 'indicator', label: '控制指标', fields: ['control_indicator'] },
    { key: 'frequency', label: '检查频率', fields: ['inspection_frequency'] },
    { key: 'documents', label: '关联资料', fields: ['related_documents'] },
  ],
}
export const initializationTableColumns = (section: InitializationSection) => section === 'project' ? [] : columns[section]

/** Preserve source order within each person, without merging their assignments. */
export function groupInitializationTableRows<T extends { change: InitializationChange; personIssues?: InitializationChangeIssue[] }>(rows: T[], section: InitializationSection) {
  const groups = new Map<string, { key: string; name: string; identity: string; rows: T[] }>()
  for (const row of rows) {
    const identity = String(row.change.after.identity_card_no || '').trim()
    const key = section === 'personnel' && identity ? `person:${identity}` : `record:${row.change.key}`
    let group = groups.get(key)
    if (!group) {
      group = { key: row.change.key, name: String(row.change.after.real_name || '姓名待补充'), identity, rows: [] }
      groups.set(key, group)
    }
    group.rows.push(row)
  }
  return [...groups.values()].map(group => {
    const issues = new Map<string, InitializationChangeIssue>()
    for (const issue of group.rows.flatMap(row => row.personIssues || [])) {
      issues.set(JSON.stringify([issue.rule_id, issue.message, issue.suggestion]), issue)
    }
    return { ...group, issues: [...issues.values()] }
  })
}

export function initializationSectionTableRows(
  rows: InitializationChangeTreeRow[], section: InitializationSection, collapsed: ReadonlySet<string>,
  issues: InitializationChangeIssue[], accounts: InitializationChangePreview['existing_personnel_accounts'] = [],
) {
  const primary = initializationTableColumns(section)
  const primaryNames = new Set(primary.flatMap(column => column.fields))
  const accountsByIdentity = new Map(accounts.map(account => [account.identity_card_no, account]))
  const issuesByChange = new Map<string, InitializationChangeIssue[]>()
  for (const issue of issues) if (issue.change_key) issuesByChange.set(issue.change_key, [...(issuesByChange.get(issue.change_key) || []), issue])
  return visibleInitializationChangeTreeRows(rows.filter(row => row.change.section === section && row.change.operation !== 'applied'), collapsed).map(row => {
    const fields = initializationComparisonFields(row.change)
    const rowIssues = [...(issuesByChange.get(row.change.key) || []), ...issues.filter(issue => !issue.change_key && issue.section === section && (issue.target_record_id === row.change.record_id || !issue.target_record_id))]
    // Multiple-position warnings belong to the person header, not an assignment field.
    const personIssues = section === 'personnel' ? rowIssues.filter(issue => issue.level === 'warning' && issue.rule_id === 'personnel.multiple_positions') : []
    const fieldIssues = rowIssues.filter(issue => !personIssues.includes(issue))
    // Missing required values are normally omitted by comparison presentation, but
    // must have a real field position when the validator asks the user to fix them.
    for (const issue of fieldIssues) {
      if (issue.field_name && !fields.some(field => field.name === issue.field_name)) {
        fields.push({ name: issue.field_name, label: initializationFieldLabel(issue.field_name), before: row.change.before?.[issue.field_name], after: row.change.after[issue.field_name], changed: false })
      }
    }
    const identityField = section === 'project' ? fields[0]?.name : primary[0]?.fields[0]
    const annotated = fields.map(field => ({ ...field, issues: fieldIssues.filter(issue => (issue.field_name || identityField) === field.name) }))
    if (identityField && !annotated.some(field => field.name === identityField) && fieldIssues.some(issue => !issue.field_name)) {
      annotated.push({ name: identityField, label: initializationFieldLabel(identityField), before: undefined, after: row.change.after[identityField], changed: false, issues: fieldIssues.filter(issue => !issue.field_name) })
    }
    const account = section === 'personnel' ? accountsByIdentity.get(String(row.change.after.identity_card_no ?? '')) : undefined
    return {
      ...row, fields: annotated, account,
      cells: primary.map(column => ({ ...column, values: column.fields.flatMap(name => annotated.filter(field => field.name === name)) })),
      supplementary: section === 'project' ? [] : annotated.filter(field => !primaryNames.has(field.name)),
      issues: rowIssues, personIssues,
    }
  })
}

export function initializationResolutionValue(change: InitializationChange, resolutions: Record<string, number | null>) {
  if (!Object.prototype.hasOwnProperty.call(resolutions, change.key)) return ''
  return resolutions[change.key] === null ? 'new' : String(resolutions[change.key])
}
export function parseInitializationResolution(value: string): number | null | undefined {
  if (value === 'new') return null
  if (!value.trim()) return undefined
  const target = Number(value)
  return Number.isInteger(target) && target > 0 ? target : undefined
}
