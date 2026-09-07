import type {
  AgentCollaborationActivity,
  AgentCollaborationMember,
  AgentContentBlock,
  AgentRuntimeMessage,
  AgentRuntimeTrace,
  AgentSubagentHitlEntry,
  AgentThinkingBlock,
  AgentToolCallBlock,
  AgentToolResultBlock,
} from '@/types/agentRuntime'

const activeStatuses = new Set([
  'queued', 'creating', 'running', 'interrupting', 'awaiting_permission', 'awaiting_external_result',
])
const internalTools = new Set(['TeamCreate', 'TeamDelete', 'reset_tools', 'agent_run_status'])
const collaborationTools = new Set(['AgentInvite', 'agent_invoke', 'agent_retry_or_switch'])

export const isRuntimeActive = (trace?: AgentRuntimeTrace | null) => activeStatuses.has(trace?.status || '')
export const isInternalTool = (name: string) => internalTools.has(name)

export function parseToolInput(call: AgentToolCallBlock): Record<string, unknown> {
  try {
    const input = JSON.parse(call.input || '{}')
    return input && typeof input === 'object' && !Array.isArray(input) ? input : {}
  } catch {
    return {}
  }
}

export function findToolResult(message: AgentRuntimeMessage, id: string) {
  return message.content.find(
    (block): block is AgentToolResultBlock => block.type === 'tool_result' && block.id === id,
  )
}

export function toolPresentationState(
  call: AgentToolCallBlock, result: AgentToolResultBlock | undefined, active: boolean, interrupted: boolean,
) {
  // A recorded result takes precedence over a stale pending/asking block after reload.
  if (result && result.state !== 'running') return result.state
  if (interrupted) return 'interrupted'
  if (!active) return 'finished'
  return call.state === 'asking' ? 'asking' : 'running'
}

export function publicToolActivities(activities: AgentCollaborationActivity[]) {
  const records: AgentCollaborationActivity[] = []
  for (const activity of activities) {
    if (activity.kind !== 'tool' || !activity.tool_name || isInternalTool(activity.tool_name)) continue
    const index = activity.tool_call_id ? records.findIndex(previous =>
      previous.reply_id === activity.reply_id && previous.tool_call_id === activity.tool_call_id,
    ) : -1
    if (index < 0) records.push(activity)
    else records[index] = activity
  }
  return records
}

export type CollaborationStep = {
  key: string
  name: string
  task: string
  status: string
  activities: AgentCollaborationActivity[]
  pending: AgentSubagentHitlEntry[]
  call?: AgentToolCallBlock
  result?: AgentToolResultBlock
  replyId?: string
}

export type AgentConversationItem =
  | { kind: 'block'; key: string; message: AgentRuntimeMessage; block: AgentContentBlock }
  | { kind: 'error'; key: string; message: AgentRuntimeMessage }
  | { kind: 'collaboration'; key: string; step: CollaborationStep }

function isPublicBlock(block: AgentContentBlock) {
  if (block.type === 'text') return Boolean(block.text.trim())
  if (block.type === 'thinking') return block.state === 'streaming' || Boolean(block.thinking.trim())
  if (block.type === 'data') return Boolean(block.source.url || block.source.data)
  if (block.type === 'tool_call') return !isInternalTool(block.name) || block.state === 'asking'
  // Hints are model context (including System / Runtime State), never conversation content.
  return false
}

const memberKey = (member: AgentCollaborationMember) => `${member.worker_session_id}:${member.work_revision}`

export function isThinkingBlockActive(
  trace: AgentRuntimeTrace | null | undefined, message: AgentRuntimeMessage, block: AgentThinkingBlock,
) {
  if (!trace || trace.status !== 'running' || message.finished_at || message.finished_reason) return false
  const messages = trace.messages.filter(item => item.role === 'assistant')
  if (messages[messages.length - 1]?.id !== message.id || block.state === 'finished') return false
  if (block.state === 'streaming') return true
  // Polling/history payloads predate the per-block lifecycle. Only the last
  // thinking segment can be active, and subsequent answer/tool output settles it.
  const index = message.content.findIndex(item => item.type === 'thinking' && item.id === block.id)
  return index >= 0 && !message.content.slice(index + 1).some(item =>
    ['thinking', 'text', 'tool_call', 'tool_result'].includes(item.type),
  )
}

function memberStatus(member: AgentCollaborationMember | undefined, trace: AgentRuntimeTrace) {
  const status = member?.work_status || 'queued'
  if (['reported', 'completed', 'failed', 'interrupted'].includes(status)) return status
  if (!isRuntimeActive(trace)) return trace.status === 'interrupted' ? 'interrupted' : 'finished'
  return status
}

/** Derive the user-facing conversation without modifying the diagnostic trace. */
export function agentConversationItems(trace?: AgentRuntimeTrace | null): AgentConversationItem[] {
  if (!trace) return []
  const claimedMembers = new Set<string>()
  const claimedPending = new Set<AgentSubagentHitlEntry>()
  const pending = isRuntimeActive(trace) ? trace.subagentHitl : []
  const messages = trace.messages.filter(message => message.role === 'assistant')
  const groups = messages.map(message => {
    const items: AgentConversationItem[] = []
    for (const block of message.content) {
      if (!isPublicBlock(block)) continue
      const key = `${message.id}:${block.type}:${block.id}`
      if (block.type !== 'tool_call' || !collaborationTools.has(block.name)) {
        items.push({ kind: 'block', key, message, block })
        continue
      }
      const input = parseToolInput(block)
      const result = findToolResult(message, block.id)
      const rawMetadata = result?.metadata?.collaboration_member
      const metadata = rawMetadata && typeof rawMetadata === 'object'
        ? rawMetadata as Record<string, unknown> : {}
      const sessionId = String(metadata.worker_session_id || '')
      const revision = Number(metadata.work_revision || 0)
      const targetName = String(input.target || '').split('@')[0].trim()
      const failed = result && ['error', 'denied', 'interrupted'].includes(result.state)
      let member: AgentCollaborationMember | undefined
      if (!failed && sessionId) {
        member = trace.collaborations.find(candidate => candidate.worker_session_id === sessionId
          && (!revision || candidate.work_revision === revision))
      } else if (!failed && !result) {
        // During streaming the member event can precede the tool result. Never borrow a
        // later assignment for a completed invocation with a different work revision.
        const candidates = trace.collaborations.filter(candidate => !claimedMembers.has(memberKey(candidate))
          && (input.agent_id ? candidate.worker_agent_id === input.agent_id : candidate.worker_agent_name === targetName)
          && (!candidate.assigned_at || candidate.assigned_at >= message.created_at))
        if (candidates.length === 1) member = candidates[0]
      }
      if (member) claimedMembers.add(memberKey(member))
      const entries = member ? pending.filter(entry => entry.worker_session_id === member.worker_session_id
        && (!member.reply_id || entry.reply_id === member.reply_id)) : []
      entries.forEach(entry => claimedPending.add(entry))
      let status = failed ? result.state : memberStatus(member, trace)
      if (block.state === 'asking' && !result && isRuntimeActive(trace)) status = 'asking'
      // A successful dispatch confirms acceptance, not successful completion of the work.
      if (!member && revision && trace.collaborations.some(candidate =>
        candidate.worker_session_id === sessionId && candidate.work_revision > revision)) status = 'finished'
      const step: CollaborationStep = {
        key,
        name: member?.worker_agent_name || String(metadata.worker_agent_name || targetName || '协同智能体'),
        task: String(input.task || input.prompt || ''),
        status,
        activities: publicToolActivities(member?.activities || []),
        pending: entries,
        call: block, result, replyId: message.id,
      }
      items.push({ kind: 'collaboration', key, step })
    }
    if (message.error) items.push({ kind: 'error', key: `${message.id}:error`, message })
    return { message, items }
  })

  // Nested delegations can arrive without a root tool call. Insert them at their
  // assignment time between replies, rather than collecting them in a top panel.
  const extra: Array<{ at: string; item: AgentConversationItem }> = []
  for (const member of trace.collaborations) {
    if (claimedMembers.has(memberKey(member))) continue
    const entries = pending.filter(entry => !claimedPending.has(entry)
      && entry.worker_session_id === member.worker_session_id
      && (!member.reply_id || entry.reply_id === member.reply_id))
    entries.forEach(entry => claimedPending.add(entry))
    const key = `member:${memberKey(member)}`
    extra.push({ at: member.assigned_at || member.started_at || member.updated_at, item: {
      kind: 'collaboration', key, step: {
        key, name: member.worker_agent_name, task: '', status: memberStatus(member, trace),
        activities: publicToolActivities(member.activities), pending: entries,
      },
    } })
  }
  for (const entry of pending) {
    if (claimedPending.has(entry)) continue
    const key = `confirmation:${entry.worker_session_id}:${entry.reply_id}`
    extra.push({ at: entry.created_at, item: { kind: 'collaboration', key, step: {
      key, name: entry.worker_agent_name, task: '', status: 'waiting', activities: [], pending: [entry],
    } } })
  }
  extra.sort((a, b) => a.at.localeCompare(b.at))
  const items: AgentConversationItem[] = []
  for (const group of groups) {
    while (extra.length && extra[0].at <= group.message.created_at) items.push(extra.shift()!.item)
    items.push(...group.items)
  }
  items.push(...extra.map(entry => entry.item))
  return items
}
