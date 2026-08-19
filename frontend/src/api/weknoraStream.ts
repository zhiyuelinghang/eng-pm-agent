import { apiBaseUrl } from './client'

export type WeKnoraStreamReference = Record<string, unknown>

export type WeKnoraAnswerProgress = {
  delta: string
  answer: string
  done: boolean
}

export type WeKnoraStreamHandlers = {
  onSession?: (sessionId: string) => void | Promise<void>
  onStatus?: (status: string) => void | Promise<void>
  onAnswer?: (progress: WeKnoraAnswerProgress) => void | Promise<void>
  onReferences?: (references: WeKnoraStreamReference[]) => void | Promise<void>
  onTitle?: (title: string) => void | Promise<void>
  onComplete?: () => void | Promise<void>
}

export type WeKnoraStreamResult = {
  sessionId: string
  answer: string
  references: WeKnoraStreamReference[]
  sessionTitle: string
}

export class WeKnoraStreamError extends Error {
  statusCode: number

  constructor(message: string, statusCode = 500) {
    super(message)
    this.name = 'WeKnoraStreamError'
    this.statusCode = statusCode
  }
}

function requestUrl(projectId: string): string {
  const base = apiBaseUrl.replace(/\/$/, '')
  return `${base}/projects/${encodeURIComponent(projectId)}/engineering-documents/ask/stream`
}

function eventStatus(event: Record<string, unknown>): string {
  const content = typeof event.content === 'string' ? event.content.trim() : ''
  const looksTechnical = /[{}\[\]\n]|\b(?:tool|function|arguments)\b|[a-z]+_[a-z]+/i.test(content)
  if (content && content.length <= 100 && !looksTechnical) return content
  if (event.done === true) return '资料检索完成，正在组织回答…'
  return '正在检索项目资料…'
}

export async function streamEngineeringKnowledgeAnswer(
  projectId: string,
  body: {
    query: string
    knowledge_base_ids?: string[]
    knowledge_ids?: string[]
    session_id?: string
  },
  handlers: WeKnoraStreamHandlers = {},
  signal?: AbortSignal,
): Promise<WeKnoraStreamResult> {
  const token = sessionStorage.getItem('access_token')
  const response = await fetch(requestUrl(projectId), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
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
    throw new WeKnoraStreamError(detail, response.status)
  }
  if (!response.body) throw new WeKnoraStreamError('浏览器未收到 WeKnora 事件流。')

  const result: WeKnoraStreamResult = {
    sessionId: body.session_id || '',
    answer: '',
    references: [],
    sessionTitle: '',
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let dataLines: string[] = []

  const dispatch = async () => {
    if (!dataLines.length) return
    const raw = dataLines.join('\n')
    dataLines = []
    let event: Record<string, unknown>
    try {
      event = JSON.parse(raw)
    } catch {
      throw new WeKnoraStreamError(`平台返回了无法解析的 WeKnora 事件：${raw.slice(0, 300)}`)
    }
    const responseType = typeof event.response_type === 'string' ? event.response_type : ''
    const remoteSessionId = typeof event.session_id === 'string' ? event.session_id.trim() : ''
    if (remoteSessionId && remoteSessionId !== result.sessionId) {
      result.sessionId = remoteSessionId
      await handlers.onSession?.(remoteSessionId)
    }
    if (responseType === 'agent_query') {
      await handlers.onStatus?.(eventStatus(event))
    } else if (responseType === 'answer') {
      const delta = typeof event.content === 'string' ? event.content : ''
      result.answer += delta
      await handlers.onAnswer?.({ delta, answer: result.answer, done: event.done === true })
    } else if (responseType === 'references') {
      const references = Array.isArray(event.knowledge_references)
        ? event.knowledge_references.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
        : []
      result.references.push(...references)
      await handlers.onReferences?.([...result.references])
    } else if (responseType === 'session_title') {
      const title = typeof event.content === 'string' ? event.content.trim() : ''
      if (title) {
        result.sessionTitle = title
        await handlers.onTitle?.(title)
      }
    } else if (responseType === 'error') {
      throw new WeKnoraStreamError(
        typeof event.content === 'string' && event.content.trim()
          ? event.content
          : 'WeKnora 智能体返回错误。',
        Number(event.status_code) || 502,
      )
    } else if (responseType === 'complete' || responseType === 'stop') {
      await handlers.onComplete?.()
    }
  }

  const consumeLine = async (line: string) => {
    if (line === '') {
      await dispatch()
      return
    }
    if (line.startsWith(':')) return
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
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
    await dispatch()
  } catch (error) {
    try {
      await reader.cancel()
    } catch {
      // The browser already closed an aborted response body.
    }
    throw error
  } finally {
    reader.releaseLock()
  }
  return result
}
