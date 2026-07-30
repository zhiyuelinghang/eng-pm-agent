export type AgentTextBlock = {
  type: 'text'
  id: string
  text: string
}

export type AgentThinkingBlock = {
  type: 'thinking'
  id: string
  thinking: string
}

export type AgentDataBlock = {
  type: 'data'
  id: string
  name?: string | null
  source: {
    type: 'base64' | 'url'
    media_type: string
    data?: string
    url?: string
  }
}

export type AgentHintBlock = {
  type: 'hint'
  id: string
  source?: string | null
  hint: string | Array<AgentTextBlock | AgentDataBlock>
}

export type AgentToolCallBlock = {
  type: 'tool_call'
  id: string
  name: string
  input: string
  state: 'pending' | 'asking' | 'allowed' | 'submitted' | 'finished'
  suggested_rules?: Array<Record<string, unknown>>
}

export type AgentToolResultBlock = {
  type: 'tool_result'
  id: string
  name: string
  output: string | Array<AgentTextBlock | AgentDataBlock>
  state: 'success' | 'error' | 'interrupted' | 'denied' | 'running'
  metadata?: Record<string, unknown>
}

export type AgentContentBlock =
  | AgentTextBlock
  | AgentThinkingBlock
  | AgentDataBlock
  | AgentHintBlock
  | AgentToolCallBlock
  | AgentToolResultBlock

export type AgentRuntimeMessage = {
  id: string
  name: string
  role: 'assistant' | 'user' | 'system'
  content: AgentContentBlock[]
  created_at: string
  finished_at?: string | null
  finished_reason?: string | null
  usage?: { input_tokens: number; output_tokens: number } | null
  error?: { type?: string; message?: string } | null
  model_names?: string[]
}

export type AgentTask = {
  id: string | number
  subject: string
  state: 'pending' | 'in_progress' | 'completed' | string
  blocked_by?: Array<string | number>
}

export type AgentTasksContext = {
  tasks: AgentTask[]
}

export type AgentSubagentHitlEntry = {
  worker_session_id: string
  worker_agent_id: string
  worker_agent_name: string
  reply_id: string
  event_type: 'require_user_confirm' | 'require_external_execution'
  event: {
    tool_calls?: AgentToolCallBlock[]
    [key: string]: unknown
  }
  created_at: string
}

export type AgentRuntimeTrace = {
  messages: AgentRuntimeMessage[]
  modelNames: string[]
  tasksContext: AgentTasksContext | null
  teamUpdateCount: number
  subagentHitl: AgentSubagentHitlEntry[]
  status: string
}

export type AgentRuntimeEvent = {
  type: string
  reply_id?: string
  created_at?: string
  [key: string]: unknown
}

export type ApiAgentMessage = {
  id: number
  conversation_id?: number
  role: 'assistant' | 'user'
  content: string
  created_at: string
  extra_data?: Record<string, unknown>
}

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T

export function createEmptyRuntimeTrace(status = 'running'): AgentRuntimeTrace {
  return {
    messages: [],
    modelNames: [],
    tasksContext: null,
    teamUpdateCount: 0,
    subagentHitl: [],
    status,
  }
}

function isRuntimeMessage(value: unknown): value is AgentRuntimeMessage {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<AgentRuntimeMessage>
  return typeof candidate.id === 'string' && Array.isArray(candidate.content)
}

export function runtimeTraceFromExtraData(
  extraData?: Record<string, unknown>,
): AgentRuntimeTrace | null {
  if (!extraData) return null
  const collection = Array.isArray(extraData.agentscope_messages)
    ? extraData.agentscope_messages.filter(isRuntimeMessage)
    : isRuntimeMessage(extraData.agentscope_message)
      ? [extraData.agentscope_message]
      : []
  if (!collection.length) return null
  const summary = (
    extraData.runtime_trace && typeof extraData.runtime_trace === 'object'
      ? extraData.runtime_trace
      : {}
  ) as Record<string, unknown>
  const modelNames = Array.isArray(summary.model_names)
    ? summary.model_names.map(String).filter(Boolean)
    : []
  const tasksContext = (
    summary.tasks_context && typeof summary.tasks_context === 'object'
      ? summary.tasks_context
      : null
  ) as AgentTasksContext | null
  const subagentHitl = Array.isArray(summary.subagent_hitl)
    ? summary.subagent_hitl as AgentSubagentHitlEntry[]
    : []
  const messages = clone(collection)
  if (modelNames.length && messages.length) {
    messages[messages.length - 1].model_names = modelNames
  }
  return {
    messages,
    modelNames,
    tasksContext,
    teamUpdateCount: Number(summary.team_update_count) || 0,
    subagentHitl: clone(subagentHitl),
    status: String(extraData.status || 'completed'),
  }
}

function findBlock<T extends AgentContentBlock['type']>(
  message: AgentRuntimeMessage,
  type: T,
  id: string,
): Extract<AgentContentBlock, { type: T }> | undefined {
  return message.content.find(
    (block): block is Extract<AgentContentBlock, { type: T }> =>
      block.type === type && block.id === id,
  )
}

function ensureReply(
  trace: AgentRuntimeTrace,
  event: AgentRuntimeEvent,
): AgentRuntimeMessage | null {
  const replyId = String(event.reply_id || '')
  if (!replyId) return trace.messages[trace.messages.length - 1] ?? null
  let message = trace.messages.find(item => item.id === replyId)
  if (!message) {
    message = {
      id: replyId,
      name: String(event.name || '智能体'),
      role: 'assistant',
      content: [],
      created_at: String(event.created_at || new Date().toISOString()),
    }
    trace.messages.push(message)
  }
  return message
}

export function applyAgentRuntimeEvent(
  current: AgentRuntimeTrace | null,
  incoming: AgentRuntimeEvent,
): AgentRuntimeTrace {
  const trace = clone(current || createEmptyRuntimeTrace())
  const event = incoming as Record<string, any>

  if (event.type === 'CUSTOM') {
    if (event.name === 'state_updated' && event.value?.tasks_context) {
      trace.tasksContext = event.value.tasks_context as AgentTasksContext
    } else if (event.name === 'team_updated') {
      trace.teamUpdateCount += 1
    } else if (event.name === 'subagent_require_user_confirm' && event.value) {
      const entry = event.value as AgentSubagentHitlEntry
      const key = `${entry.worker_session_id}:${entry.reply_id}`
      trace.subagentHitl = [
        ...trace.subagentHitl.filter(
          item => `${item.worker_session_id}:${item.reply_id}` !== key,
        ),
        entry,
      ]
    } else if (event.name === 'subagent_user_confirm_result' && event.value) {
      const resolved = event.value as Pick<
        AgentSubagentHitlEntry,
        'worker_session_id' | 'reply_id'
      >
      const key = `${resolved.worker_session_id}:${resolved.reply_id}`
      trace.subagentHitl = trace.subagentHitl.filter(
        item => `${item.worker_session_id}:${item.reply_id}` !== key,
      )
    }
    return trace
  }

  if (event.type === 'REPLY_START') {
    const replyId = String(event.reply_id)
    if (!trace.messages.some(item => item.id === replyId)) {
      trace.messages.push({
        id: replyId,
        name: String(event.name || '智能体'),
        role: 'assistant',
        content: [],
        created_at: String(event.created_at || new Date().toISOString()),
      })
    }
    trace.status = 'running'
    return trace
  }

  const message = ensureReply(trace, incoming)
  if (!message) return trace

  switch (event.type) {
    case 'REPLY_END':
      message.finished_at = String(event.created_at || new Date().toISOString())
      message.finished_reason = String(event.finished_reason || 'completed')
      message.error = event.error || null
      trace.status = message.error
        ? 'error'
        : message.finished_reason === 'interrupted'
          ? 'interrupted'
          : 'completed'
      break
    case 'MODEL_CALL_START': {
      const modelName = String(event.model_name || '')
      if (modelName && !trace.modelNames.includes(modelName)) {
        trace.modelNames.push(modelName)
      }
      message.model_names = [...trace.modelNames]
      break
    }
    case 'MODEL_CALL_END':
      message.usage = message.usage || { input_tokens: 0, output_tokens: 0 }
      message.usage.input_tokens += Number(event.input_tokens) || 0
      message.usage.output_tokens += Number(event.output_tokens) || 0
      break
    case 'TEXT_BLOCK_START':
      message.content.push({
        type: 'text',
        id: String(event.block_id),
        text: '',
      })
      break
    case 'TEXT_BLOCK_DELTA': {
      const block = findBlock(message, 'text', String(event.block_id))
      if (block) block.text += String(event.delta || '')
      break
    }
    case 'THINKING_BLOCK_START':
      message.content.push({
        type: 'thinking',
        id: String(event.block_id),
        thinking: '',
      })
      break
    case 'THINKING_BLOCK_DELTA': {
      const block = findBlock(message, 'thinking', String(event.block_id))
      if (block) block.thinking += String(event.delta || '')
      break
    }
    case 'DATA_BLOCK_START':
      message.content.push({
        type: 'data',
        id: String(event.block_id),
        source: {
          type: 'base64',
          data: '',
          media_type: String(event.media_type || 'application/octet-stream'),
        },
      })
      break
    case 'DATA_BLOCK_DELTA': {
      const block = findBlock(message, 'data', String(event.block_id))
      if (block && block.source.type === 'base64') {
        block.source.data = `${block.source.data || ''}${String(event.data || '')}`
      }
      break
    }
    case 'HINT_BLOCK':
      message.content.push({
        type: 'hint',
        id: String(event.block_id),
        source: event.source == null ? null : String(event.source),
        hint: event.hint as AgentHintBlock['hint'],
      })
      break
    case 'TOOL_CALL_START':
      message.content.push({
        type: 'tool_call',
        id: String(event.tool_call_id),
        name: String(event.tool_call_name || 'Tool'),
        input: '',
        state: 'pending',
        suggested_rules: [],
      })
      break
    case 'TOOL_CALL_DELTA': {
      const block = findBlock(message, 'tool_call', String(event.tool_call_id))
      if (block) block.input += String(event.delta || '')
      break
    }
    case 'TOOL_RESULT_START':
      message.content.push({
        type: 'tool_result',
        id: String(event.tool_call_id),
        name: String(event.tool_call_name || 'Tool'),
        output: [],
        state: 'running',
      })
      break
    case 'TOOL_RESULT_TEXT_DELTA': {
      const block = findBlock(message, 'tool_result', String(event.tool_call_id))
      if (!block) break
      if (typeof block.output === 'string') {
        block.output = [{ type: 'text', id: `${block.id}-text`, text: block.output }]
      }
      const last = block.output[block.output.length - 1]
      if (last?.type === 'text') {
        last.text += String(event.delta || '')
      } else {
        block.output.push({
          type: 'text',
          id: `${block.id}-text-${block.output.length}`,
          text: String(event.delta || ''),
        })
      }
      break
    }
    case 'TOOL_RESULT_DATA_DELTA': {
      const block = findBlock(message, 'tool_result', String(event.tool_call_id))
      if (!block) break
      if (typeof block.output === 'string') {
        block.output = [{ type: 'text', id: `${block.id}-text`, text: block.output }]
      }
      block.output.push({
        type: 'data',
        id: String(event.block_id || `${block.id}-data-${block.output.length}`),
        source: event.url
          ? {
              type: 'url',
              url: String(event.url),
              media_type: String(event.media_type || 'application/octet-stream'),
            }
          : {
              type: 'base64',
              data: String(event.data || ''),
              media_type: String(event.media_type || 'application/octet-stream'),
            },
      })
      break
    }
    case 'TOOL_RESULT_END': {
      const result = findBlock(message, 'tool_result', String(event.tool_call_id))
      if (result) {
        result.state = event.state || 'success'
        result.metadata = event.metadata || {}
      }
      const call = findBlock(message, 'tool_call', String(event.tool_call_id))
      if (call) call.state = 'finished'
      break
    }
    case 'REQUIRE_USER_CONFIRM':
      for (const incomingCall of event.tool_calls || []) {
        const call = findBlock(message, 'tool_call', String(incomingCall.id))
        if (call) {
          call.state = 'asking'
          call.suggested_rules = incomingCall.suggested_rules || []
        }
      }
      trace.status = 'awaiting_permission'
      break
    case 'REQUIRE_EXTERNAL_EXECUTION':
      for (const incomingCall of event.tool_calls || []) {
        const call = findBlock(message, 'tool_call', String(incomingCall.id))
        if (call) call.state = 'submitted'
      }
      trace.status = 'awaiting_external_result'
      break
    case 'EXCEED_MAX_ITERS':
      message.finished_reason = 'exceed_max_iters'
      break
  }
  return trace
}
