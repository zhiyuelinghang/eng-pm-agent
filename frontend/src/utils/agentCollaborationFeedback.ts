import type { AgentHintBlock, AgentRuntimeMessage, AgentRuntimeTrace } from '@/types/agentRuntime'

export type CollaborationFeedback = {
  name: string
  teamName: string
  text: string
  workerSessionId: string
  workRevision: number
}
type FeedbackMember = Omit<CollaborationFeedback, 'text'> & { assignedAt: string }

/** Include older assignments preserved in call results, without borrowing a later run. */
export function collaborationFeedbackMembers(trace: AgentRuntimeTrace): FeedbackMember[] {
  const members = new Map<string, FeedbackMember>()
  function add(data: Record<string, unknown>, fallbackAt: string) {
    const workerSessionId = String(data.worker_session_id || '')
    const name = String(data.worker_agent_name || '').trim()
    const workRevision = Number(data.work_revision) || 0
    if (!workerSessionId || !name) return
    const key = `${workerSessionId}:${workRevision}`
    if (members.has(key)) return
    members.set(key, {
      workerSessionId, workRevision, name, teamName: String(data.team_name || ''),
      assignedAt: String(data.assigned_at || data.started_at || fallbackAt || ''),
    })
  }
  for (const member of trace.collaborations) add({ ...member }, member.updated_at)
  for (const message of trace.messages) {
    for (const block of message.content) {
      if (block.type !== 'tool_result') continue
      const metadata = block.metadata?.collaboration_member
      if (metadata && typeof metadata === 'object' && !Array.isArray(metadata)) add(metadata as Record<string, unknown>, message.created_at)
    }
  }
  return [...members.values()]
}

/** Only a complete team-message envelope from an identified assigned member is public. */
export function parseCollaborationFeedback(block: AgentHintBlock, message: AgentRuntimeMessage, members: FeedbackMember[]): CollaborationFeedback | null {
  if (typeof block.hint !== 'string' || message.role === 'system') return null
  const envelope = block.hint.match(/^\s*<team-message\s+from=(["'])([^"'<>]+)\1>\s*([\s\S]*?)\s*<\/team-message>\s*$/i)
  if (!envelope) return null
  const sender = envelope[2].trim(), text = envelope[3].trim()
  if (!text || /^(system|runtime state)$/i.test(sender) || /<\/?(?:system-reminder|system|runtime-state|team-message)\b/i.test(text)) return null
  const source = block.source?.trim()
  if (!source) return null
  if (source !== sender) {
    try {
      const parsed: unknown = JSON.parse(source)
      if (!parsed || typeof parsed !== 'object' || !('label' in parsed) || parsed.label !== 'team_message') return null
      if ('sublabel' in parsed && parsed.sublabel !== sender) return null
    } catch { return null }
  }
  const receivedAt = Date.parse(message.created_at)
  if (!Number.isFinite(receivedAt)) return null
  const candidates = members.filter(member => member.name === sender
    && Number.isFinite(Date.parse(member.assignedAt)) && Date.parse(member.assignedAt) <= receivedAt)
    .sort((a, b) => Date.parse(b.assignedAt) - Date.parse(a.assignedAt))
  const member = candidates[0]
  if (!member) return null
  // A name shared by distinct worker sessions cannot identify the sender safely.
  if (new Set(candidates.map(candidate => candidate.workerSessionId)).size !== 1) return null
  if (candidates[1] && candidates[1].assignedAt === member.assignedAt && candidates[1].workRevision !== member.workRevision) return null
  return { name: member.name, teamName: member.teamName, text, workerSessionId: member.workerSessionId, workRevision: member.workRevision }
}
