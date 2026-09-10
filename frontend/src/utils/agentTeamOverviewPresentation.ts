import type { AgentCollaborationMember, AgentRuntimeTrace } from '@/types/agentRuntime'

export type AgentTeamOverviewMember = {
  id: string
  name: string
  revision: number
  state: string
  stateLabel: string
  activity: string
  completed: boolean
  running: boolean
  failed: boolean
}
export type AgentTeamOverview = {
  id: string
  name: string
  members: AgentTeamOverviewMember[]
  completedCount: number
}

const completedStates = new Set(['reported', 'completed'])
const unsettledStates = new Set(['idle', 'queued', 'running', 'waiting', 'asking'])
const stoppedTraceStates = new Set(['interrupted', 'interrupting'])
const activeTraceStates = new Set(['queued', 'creating', 'running', 'awaiting_permission', 'awaiting_external_result'])
const label = (value: unknown) => typeof value === 'string' ? value.trim() : ''
const revision = (member: AgentCollaborationMember) => Number.isFinite(member.work_revision) ? member.work_revision : 0
const updatedAt = (member: AgentCollaborationMember) => Date.parse(member.updated_at || '') || 0

function presentMember(member: AgentCollaborationMember, trace: AgentRuntimeTrace): AgentTeamOverviewMember {
  const state = member.work_status
  let stateLabel = ({ idle: '等待启动', queued: '排队中', running: '处理中', waiting: '等待反馈',
    asking: '等待确认', reported: '已反馈', completed: '已完成', failed: '失败', error: '失败',
    denied: '已拒绝', interrupted: '已停止', finished: '已结束' } as Record<string, string>)[state] || '状态待确认'
  if (unsettledStates.has(state)) {
    if (stoppedTraceStates.has(trace.status)) stateLabel = '已停止'
    else if (!activeTraceStates.has(trace.status)) stateLabel = '待继续'
  }
  return {
    id: member.worker_session_id,
    name: label(member.worker_agent_name) || '协同成员',
    revision: revision(member),
    state,
    stateLabel,
    // The registered display snapshot is the only source of a public activity title.
    activity: label(member.current_activity?.presentation?.label),
    completed: completedStates.has(state),
    running: state === 'running' && trace.status === 'running',
    failed: ['failed', 'error', 'denied'].includes(state),
  }
}

/** Summarize existing teams without inventing members from dispatch tool calls or moving their timeline. */
export function agentTeamOverviewPresentation(trace?: AgentRuntimeTrace | null): AgentTeamOverview[] {
  if (!trace) return []
  const grouped = new Map<string, Map<string, AgentCollaborationMember>>()
  for (const member of trace.collaborations) {
    const teamId = label(member.team_id)
    const workerId = label(member.worker_session_id)
    if (!teamId || !workerId) continue
    const members = grouped.get(teamId) || new Map<string, AgentCollaborationMember>()
    const previous = members.get(workerId)
    if (!previous || revision(member) > revision(previous)
      || revision(member) === revision(previous) && updatedAt(member) >= updatedAt(previous)) members.set(workerId, member)
    grouped.set(teamId, members)
  }
  const teams: AgentTeamOverview[] = []
  for (const [id, latest] of grouped) {
    if (latest.size < 2) continue
    const sources = [...latest.values()]
    const name = [...sources].sort((a, b) => updatedAt(b) - updatedAt(a))
      .map(member => label(member.team_name)).find(Boolean) || '协同团队'
    const members = sources.map(member => presentMember(member, trace))
    teams.push({ id, name, members, completedCount: members.filter(member => member.completed).length })
  }
  return teams
}
