import type { AgentCollaborationActivity } from '@/types/agentRuntime'
import type { CollaborationStep } from './agentMessagePresentation'

const terminalStates = new Set(['reported', 'completed', 'failed', 'error', 'denied', 'interrupted', 'finished'])
const stateLabels: Record<string, string> = {
  queued: '等待处理', idle: '等待处理', running: '处理中', waiting: '等待反馈', asking: '等待确认',
  external: '等待处理结果', reported: '已反馈', completed: '已完成', success: '已完成', failed: '处理失败',
  error: '处理失败', denied: '已拒绝', interrupted: '已停止', interrupting: '正在停止', finished: '已结束',
}

/** Invitations may contain long implementation instructions. Only their opening task is public. */
export function collaborationTask(value: unknown, limit = 180) {
  if (typeof value !== 'string') return ''
  const line = value.trim().split(/\r?\n/).find(part => part.trim())?.trim() || ''
  const task = line.split(/必填上下文|执行规则|工具参数/)[0]
    .replace(/^(?:#{1,6}\s*)?(?:任务|task)\s*[:：]\s*/i, '')
    .replace(/[（(]\s*项目\s*ID\s*[:：]?\s*\d+\s*[）)]/gi, '')
    .replace(/[（(]\s*section\s*=\s*[a-z_]+\s*[）)]/gi, '')
    .replace(/【[a-z_]+\s*\/\s*([^】]+)】/g, '【$1】').trim()
  if (!task || /^[{[<]/.test(task) || /\b(?:draft_id|record_id|agent_id|text_limit|worker_session_id)\b/.test(task)) return ''
  return task.length > limit ? `${task.slice(0, limit - 1)}…` : task
}

export function collaborationState(step: CollaborationStep, active: boolean, interrupted = false) {
  if (terminalStates.has(step.status)) return step.status
  if (interrupted) return 'interrupted'
  if (step.status === 'interrupting') return 'interrupting'
  if (!active) return 'finished'
  if (step.pending.some(entry => entry.event_type === 'require_user_confirm') || step.status === 'asking') return 'asking'
  if (step.pending.some(entry => entry.event_type === 'require_external_execution')) return 'external'
  return stateLabels[step.status] ? step.status : 'running'
}

export const collaborationStateLabel = (state: string) => stateLabels[state] || '已结束'
export const collaborationIsWorking = (state: string) => !terminalStates.has(state) && state !== 'interrupting'
export const collaborationIsOpen = (state: string, override: boolean | null) => override ?? collaborationIsWorking(state)

export function collaborationActivityLabel(activity: AgentCollaborationActivity) {
  if (activity.kind === 'tool') return activity.presentation?.label?.trim() || '处理相关事项'
  if (activity.kind === 'started') return '开始处理分配任务'
  if (activity.kind === 'analysis') return '正在分析任务'
  if (activity.kind === 'waiting') return activity.label === '等待人工确认' ? '等待确认' : '等待处理结果'
  if (activity.kind === 'finished') return ['error', 'failed'].includes(activity.state) ? '分配任务处理失败'
    : activity.state === 'interrupted' ? '分配任务已停止' : '分配任务处理结束'
  return '处理任务'
}

export function collaborationActivityState(activity: AgentCollaborationActivity, stepState: string) {
  if (activity.state && !['running', 'queued', 'idle', 'asking', 'waiting'].includes(activity.state)) return activity.state
  return collaborationIsWorking(stepState) ? activity.state || 'running'
    : stepState === 'interrupted' || stepState === 'interrupting' ? 'interrupted' : 'finished'
}

export function collaborationElapsed(step: CollaborationStep, state: string, now = Date.now()) {
  const start = Date.parse(step.startedAt || step.assignedAt || '')
  const end = step.settledAt ? Date.parse(step.settledAt)
    : collaborationIsWorking(state) ? now : Date.parse(step.updatedAt || '')
  if (!Number.isFinite(start) || !Number.isFinite(end)) return ''
  const seconds = Math.max(0, Math.round((end - start) / 1000))
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
}

export function collaborationTime(value?: string | null) {
  const date = new Date(value || '')
  return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(date) : ''
}
