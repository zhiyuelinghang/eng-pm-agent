import type { InitializationChange, InitializationChangeIssue, InitializationChangePreview, InitializationSection } from '@/types/initializationChanges'
import { initializationComparisonFields } from './initializationChangePresentation'
import { visibleInitializationChangeTreeRows, type InitializationChangeTreeRow } from './initializationChangeTree'

export type InitializationComparisonField = ReturnType<typeof initializationComparisonFields>[number]
export type InitializationTableColumn = { key: string; label: string; fields: string[]; account?: boolean }
const columns: Record<Exclude<InitializationSection, 'project'>, InitializationTableColumn[]> = {
  personnel: [
    { key: 'identity', label: '姓名 / 岗位', fields: ['real_name', 'position_name'] },
    { key: 'account', label: '已有账号', fields: [], account: true },
    { key: 'certificate', label: '身份证 / 证书', fields: ['identity_card_no', 'certificate_no'] },
    { key: 'responsibility', label: '职责', fields: ['responsibility_description'] },
  ],
  wbs: [
    { key: 'identity', label: 'WBS 编号 / 名称', fields: ['wbs_code', 'name'] },
    { key: 'schedule', label: '计划起止', fields: ['planned_start_at', 'planned_finish_at'] },
    { key: 'duration', label: '工期', fields: ['duration_hours'] },
    { key: 'progress', label: '进度 / 状态', fields: ['progress_percent', 'status_text'] },
    { key: 'owner', label: '负责人', fields: ['assigned_to_text'] },
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

export function initializationSectionTableRows(
  rows: InitializationChangeTreeRow[], section: InitializationSection, collapsed: ReadonlySet<string>,
  issues: InitializationChangeIssue[], accounts: InitializationChangePreview['existing_personnel_accounts'] = [],
) {
  const primary = initializationTableColumns(section)
  const primaryNames = new Set(primary.flatMap(column => column.fields))
  const accountsByIdentity = new Map(accounts.map(account => [account.identity_card_no, account]))
  const issuesByChange = new Map<string, InitializationChangeIssue[]>()
  for (const issue of issues) if (issue.change_key) issuesByChange.set(issue.change_key, [...(issuesByChange.get(issue.change_key) || []), issue])
  return visibleInitializationChangeTreeRows(rows.filter(row => row.change.section === section), collapsed).map(row => {
    const fields = initializationComparisonFields(row.change)
    const account = section === 'personnel' ? accountsByIdentity.get(String(row.change.after.identity_card_no ?? '')) : undefined
    return {
      ...row, fields, account,
      cells: primary.map(column => ({ ...column, values: column.fields.flatMap(name => fields.filter(field => field.name === name)) })),
      supplementary: section === 'project' ? [] : fields.filter(field => !primaryNames.has(field.name)),
      issues: issuesByChange.get(row.change.key) || [],
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
