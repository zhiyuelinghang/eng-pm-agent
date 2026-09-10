/** Shared field labels used by both formal project data and import review. */
export function displayWbsStatusText(value?: string | null, fallback = '') {
  const raw = value?.trim() || ''
  const normalized = raw.toLowerCase().replace(/[\s-]+/g, '_')
  const translated: Record<string, string> = {
    not_started: '未开始', pending: '待处理', open: '打开', active: '活动',
    in_progress: '进行中', completed: '已完成', complete: '已完成', done: '已完成',
    delayed: '已延期', overdue: '已逾期',
  }
  return translated[normalized] || raw || fallback
}

export function displayWbsPriorityText(value?: string | null, fallback = '未设置优先级') {
  if (!value?.trim()) return fallback
  const raw = value.trim()
  const translated: Record<string, string> = {
    critical: '紧急优先级', urgent: '紧急优先级', high: '高优先级',
    medium: '中优先级', normal: '普通优先级', low: '低优先级',
  }
  return translated[raw.toLowerCase()] || (raw.includes('优先级') ? raw : `${raw}优先级`)
}

export function displayWbsItemType(value?: string | null) {
  const raw = value?.trim() || ''
  const normalized = raw.toLowerCase().replace(/[\s_-]+/g, '')
  const translated: Record<string, string> = {
    project: '项目', summary: '汇总任务', summarytask: '汇总任务',
    taskgroup: '任务组', group: '任务组', task: '任务', milestone: '里程碑',
  }
  return translated[normalized] || raw
}

export function formatInitializationDate(value?: string | null) {
  return value ? value.slice(0, 10) : ''
}

export function formatInitializationDateTime(value: string) {
  // Preserve time, sub-second precision and offset so review never hides a
  // changed instant. Only date-only and exact midnight values use the short form.
  if (/^\d{4}-\d{2}-\d{2}(?:T| )00:00:00(?:\.0+)?$/.test(value)) return formatInitializationDate(value)
  return value.replace(/^(\d{4}-\d{2}-\d{2})T/, '$1 ')
}
