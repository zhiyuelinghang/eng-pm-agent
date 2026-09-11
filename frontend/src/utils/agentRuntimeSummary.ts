import type { AgentRuntimeTrace } from '@/types/agentRuntime'

/** Summarize the persisted turn; never estimate provider token usage. */
export function agentRuntimeSummary(trace?: AgentRuntimeTrace | null) {
  const messages = trace?.messages.filter(message => message.role === 'assistant') || []
  const modelNames = [...new Set([...(trace?.modelNames || []), ...messages.flatMap(message => message.model_names || [])])]
  const measured = messages.filter(message => message.usage)
  const usage = measured.length ? measured.reduce((sum, message) => ({
    input: sum.input + (message.usage?.input_tokens || 0),
    output: sum.output + (message.usage?.output_tokens || 0),
  }), { input: 0, output: 0 }) : null
  const outputLength = messages.reduce((sum, message) => sum + message.content.reduce((size, block) => size + (block.type === 'text' ? Array.from(block.text).length : 0), 0), 0)
  const latest = new Map<string, NonNullable<AgentRuntimeTrace>['collaborations'][number]>()
  for (const member of trace?.collaborations || []) {
    const key = `${member.team_id}:${member.worker_session_id}`
    const previous = latest.get(key)
    if (!previous || member.work_revision > previous.work_revision || member.work_revision === previous.work_revision && member.updated_at >= previous.updated_at) latest.set(key, member)
  }
  const waitingNames = [...new Set([...latest.values()].filter(member => ['queued', 'running', 'waiting', 'asking'].includes(member.work_status) || member.work_status === 'idle' && !member.settled_at).map(member => member.worker_agent_name).filter(Boolean))]
  return { modelNames, usage, outputLength, waitingNames }
}
