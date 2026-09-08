import type { AgentRuntimeTrace, AgentToolCallBlock } from '@/types/agentRuntime'
import { agentConversationItems, findToolResult, isRuntimeActive, toolPresentationState } from './agentMessagePresentation'
import type { AgentWorkPresentation } from '@/types/agentRuntime'

/** Old records without a snapshot remain visible without revealing raw names. */
export function userWorkLabel(presentation?: AgentWorkPresentation | null) {
  return presentation?.label?.trim() || '处理相关事项'
}

export function userWorkState(state: string, active: boolean, interrupted = false) {
  if (['success', 'completed', 'reported', 'error', 'failed', 'denied', 'interrupted', 'finished'].includes(state)) return state
  if (interrupted) return 'interrupted'
  return active ? state : 'finished'
}

/** Preserve the conversation timeline; hide execution plumbing, not work records. */
export function userMessagePresentation(trace?: AgentRuntimeTrace | null, streaming = false) {
  const active = isRuntimeActive(trace) || streaming
  const items = agentConversationItems(trace)
  const answers = items.filter(item => item.kind === 'block' && ['text', 'data'].includes(item.block.type))
  const confirmations: Array<{ key: string; replyId: string; call: AgentToolCallBlock }> = []
  const addConfirmation = (replyId: string, call: AgentToolCallBlock) => {
    const key = `${replyId}:${call.id}`
    if (!confirmations.some(item => item.key === key)) confirmations.push({ key, replyId, call })
  }
  if (active && !['interrupted', 'interrupting'].includes(trace?.status || '')) {
    for (const item of items) {
      if (item.kind === 'block' && item.block.type === 'tool_call') {
        if (trace?.status !== 'awaiting_external_result' && toolPresentationState(item.block, findToolResult(item.message, item.block.id), active, false) === 'asking') addConfirmation(item.message.id, item.block)
      } else if (item.kind === 'collaboration') {
        if (item.step.call && toolPresentationState(item.step.call, item.step.result, active, false) === 'asking') addConfirmation(item.step.replyId || '', item.step.call)
        for (const entry of item.step.pending) {
          if (entry.event_type === 'require_user_confirm') for (const call of entry.event.tool_calls || []) addConfirmation(entry.reply_id, call)
        }
      }
    }
  }
  let workingLabel = 'Dobby 正在处理请求…'
  if (trace?.status === 'interrupting') workingLabel = 'Dobby 正在停止处理…'
  else if (confirmations.length || trace?.status === 'awaiting_permission') workingLabel = '等待你确认后继续'
  else if (trace?.status === 'awaiting_external_result') workingLabel = 'Dobby 正在等待处理结果…'
  else {
    const messages = trace?.messages.filter(message => message.role === 'assistant') || []
    const latest = messages[messages.length - 1]
    const pending = latest?.content.filter((block): block is AgentToolCallBlock => block.type === 'tool_call'
      && toolPresentationState(block, findToolResult(latest, block.id), active, false) === 'running') || []
    const current = pending[pending.length - 1]
    if (current) workingLabel = `Dobby 正在：${userWorkLabel(current.presentation)}…`
    else if (trace?.collaborations.some(member => ['queued', 'running', 'idle'].includes(member.work_status))) workingLabel = 'Dobby 正在协同整理信息…'
    else if (latest?.content.some(block => block.type === 'thinking')) workingLabel = 'Dobby 正在整理思路…'
  }
  return { items, answers, confirmations, workingLabel }
}
