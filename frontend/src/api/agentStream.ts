import { apiBaseUrl } from './client'
import type { AgentRuntimeEvent, ApiAgentMessage } from '@/types/agentRuntime'

export type AgentStreamAccepted = {
  conversation_id: number
  user_message: ApiAgentMessage
  runtime_status: string
}

export type AgentStreamDone = {
  message: ApiAgentMessage
  runtime_status: string
}

export type AgentStreamHandlers = {
  onAccepted?: (payload: AgentStreamAccepted) => void | Promise<void>
  onEvent?: (event: AgentRuntimeEvent) => void | Promise<void>
  onDone?: (payload: AgentStreamDone) => void | Promise<void>
}

export class AgentStreamError extends Error {
  statusCode: number

  constructor(message: string, statusCode = 500) {
    super(message)
    this.name = 'AgentStreamError'
    this.statusCode = statusCode
  }
}

function streamUrl(conversationId: number): string {
  const base = apiBaseUrl.replace(/\/$/, '')
  return `${base}/agent-conversations/${conversationId}/messages/stream`
}

async function dispatchFrame(
  eventName: string,
  dataLines: string[],
  handlers: AgentStreamHandlers,
): Promise<void> {
  if (!dataLines.length) return
  const raw = dataLines.join('\n')
  let payload: any
  try {
    payload = JSON.parse(raw)
  } catch {
    throw new AgentStreamError(`平台返回了无法解析的流式事件：${raw.slice(0, 300)}`)
  }
  if (eventName === 'accepted') {
    await handlers.onAccepted?.(payload as AgentStreamAccepted)
  } else if (eventName === 'agent_event') {
    await handlers.onEvent?.(payload as AgentRuntimeEvent)
  } else if (eventName === 'done') {
    await handlers.onDone?.(payload as AgentStreamDone)
  } else if (eventName === 'error') {
    throw new AgentStreamError(
      String(payload?.detail || '智能体流式处理失败'),
      Number(payload?.status_code) || 500,
    )
  }
}

export async function streamAgentConversationMessage(
  conversationId: number,
  content: string,
  handlers: AgentStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = sessionStorage.getItem('access_token')
  const response = await fetch(streamUrl(conversationId), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ content }),
    signal,
  })
  if (!response.ok) {
    let detail = response.statusText
    const raw = await response.text()
    try {
      const payload = JSON.parse(raw)
      detail = String(payload?.detail || payload?.message || detail)
    } catch {
      detail = raw || detail
    }
    throw new AgentStreamError(detail, response.status)
  }
  if (!response.body) {
    throw new AgentStreamError('浏览器未收到智能体事件流。')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let eventName = 'message'
  let dataLines: string[] = []

  const consumeLine = async (line: string) => {
    if (line === '') {
      await dispatchFrame(eventName, dataLines, handlers)
      eventName = 'message'
      dataLines = []
      return
    }
    if (line.startsWith(':')) return
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim() || 'message'
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart())
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split(/\r?\n/)
      buffer = lines.pop() || ''
      for (const line of lines) await consumeLine(line)
    }
    buffer += decoder.decode()
    if (buffer) await consumeLine(buffer)
    if (dataLines.length) await dispatchFrame(eventName, dataLines, handlers)
  } finally {
    reader.releaseLock()
  }
}
