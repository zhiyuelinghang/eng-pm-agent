import type { InitializationChange, InitializationChangeIssue, InitializationDraftReference } from '@/types/initializationChanges'
import { initializationChangeTitle, initializationFieldLabel } from './initializationChangePresentation'

export type ReviewIssue = InitializationChangeIssue & { key: string; location: string; selected: boolean }

export function initializationReviewIssues(draft: InitializationDraftReference | null, changes: InitializationChange[], previewIssues: InitializationChangeIssue[], selectedKeys: string[], previewCompleted = false): ReviewIssue[] {
  const result = new Map<string, ReviewIssue>()
  const selected = new Set(selectedKeys)
  for (const [index, issue] of [...(draft?.validation_issues || []), ...previewIssues].entries()) {
    const change = changes.find(row => issue.change_key ? row.key === issue.change_key : row.section === issue.section && row.record_id === issue.target_record_id && (!issue.field_name || row.section !== 'project' || row.fields.some(field => field.name === issue.field_name) || row.key.endsWith(':' + issue.field_name)))
    const changeKey = change?.key || issue.change_key
    if (previewCompleted && index < (draft?.validation_issues?.length || 0) && changeKey && selected.has(changeKey)) continue
    if (change?.operation === 'applied') continue
    const key = JSON.stringify([issue.rule_id || '', changeKey || issue.target_record_id || issue.section, issue.field_name, issue.message])
    const field = issue.field_name ? initializationFieldLabel(issue.field_name) : ''
    result.set(key, { ...issue, key, change_key: changeKey, selected: Boolean(changeKey && selected.has(changeKey)),
      location: [change ? initializationChangeTitle(change) || String(change.after.wbs_code || '') : '', field].filter(Boolean).join(' · ') })
  }
  return [...result.values()].sort((a, b) => Number(b.level === 'error') - Number(a.level === 'error'))
}
