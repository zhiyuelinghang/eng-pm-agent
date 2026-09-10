import type { AgentRuntimeTrace, AgentToolCallBlock, AgentToolResultBlock } from '@/types/agentRuntime'

export type AgentPlanTask = {
  id: string
  subject: string
  state: string
  owner: string
  blockedBy: string[]
}
export type AgentTaskPlan = {
  tasks: Array<AgentPlanTask & { stateLabel: string; blockers: string[] }>
  completedCount: number
  progress: number
}

const taskTools = new Set(['TaskCreate', 'TaskUpdate', 'TaskList', 'TodoWrite'])
const finishedStates = new Set(['completed', 'skipped'])
export const isTaskPlanTool = (name: string) => taskTools.has(name)

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : {}
}
function parse(value: string): unknown {
  try { return JSON.parse(value) } catch { return null }
}
function label(value: unknown) { return typeof value === 'string' ? value.trim() : '' }
function identifier(value: unknown) {
  return typeof value === 'number' || typeof value === 'string' ? String(value).trim() : ''
}
function ids(value: unknown) { return Array.isArray(value) ? [...new Set(value.map(identifier).filter(Boolean))] : [] }
function task(value: unknown, fallbackId = ''): AgentPlanTask | null {
  const source = record(value)
  const id = identifier(source.id) || fallbackId
  const subject = label(source.subject) || label(source.content)
  const state = label(source.state) || label(source.status) || 'pending'
  if (!id || !subject || state === 'deleted') return null
  return { id, subject, state, owner: label(source.owner), blockedBy: ids(source.blocked_by) }
}
function outputText(result: AgentToolResultBlock) {
  return typeof result.output === 'string' ? result.output
    : result.output.filter(block => block.type === 'text').map(block => block.text).join('\n')
}

/** TaskList's text format is defined by AgentScope/tool/_task/_list_task.py. */
function listedTasks(text: string): AgentPlanTask[] | null {
  if (text.trim() === 'No tasks available.') return []
  const parsed = parse(text)
  const rows = Array.isArray(parsed) ? parsed : record(parsed).tasks
  if (Array.isArray(rows)) return rows.map(row => task(row)).filter((row): row is AgentPlanTask => Boolean(row))
  const tasks: AgentPlanTask[] = []
  for (const line of text.split('\n').filter(line => line.trim())) {
    const match = line.match(/^([^\s]+) \[([^\]]+)\] (.+)$/)
    if (!match) return null
    let subject = match[3] || ''
    const blocked = subject.match(/\[blocked by ([^\]]*)\]$/)
    if (blocked) subject = subject.slice(0, blocked.index).trim()
    const owner = subject.match(/\(([^()]*)\)$/)
    if (owner) subject = subject.slice(0, owner.index).trim()
    const row = task({ id: match[1], subject, state: match[2], owner: owner?.[1],
      blocked_by: blocked ? (blocked[1] || '').split(',').map(value => value.trim()) : [] })
    if (row) tasks.push(row)
  }
  return tasks.length ? tasks : null
}

function applyUpdate(tasks: Map<string, AgentPlanTask>, input: Record<string, unknown>) {
  const id = identifier(input.task_id)
  const previous = tasks.get(id)
  if (!previous) return
  if (input.status === 'deleted') {
    tasks.delete(id)
    for (const row of tasks.values()) row.blockedBy = row.blockedBy.filter(blocker => blocker !== id)
    return
  }
  previous.subject = label(input.subject) || previous.subject
  previous.state = label(input.status) || previous.state
  if (typeof input.owner === 'string') previous.owner = input.owner.trim()
  previous.blockedBy = [...new Set([...previous.blockedBy, ...ids(input.add_blocked_by).filter(value => tasks.has(value))])]
  for (const blockedId of ids(input.add_blocks)) {
    const blocked = tasks.get(blockedId)
    if (blocked && !blocked.blockedBy.includes(id)) blocked.blockedBy.push(id)
  }
}

/** Old histories may lack a state snapshot; only successful tool results change their plan. */
function reconstructTasks(trace: AgentRuntimeTrace) {
  const tasks = new Map<string, AgentPlanTask>()
  for (const message of trace.messages.filter(message => message.role === 'assistant')) {
    for (const block of message.content) {
      if (block.type !== 'tool_call' || !isTaskPlanTool(block.name)) continue
      const result = message.content.find((item): item is AgentToolResultBlock =>
        item.type === 'tool_result' && item.id === block.id)
      if (result?.state !== 'success') continue
      const input = record(parse(block.input || '{}'))
      const output = outputText(result)
      if (block.name === 'TaskCreate') {
        const resultTask = record(parse(output))
        const id = identifier(record(resultTask.task).id) || identifier(resultTask.id)
          || output.match(/Task \(id=([^\)]+)\) created successfully:/)?.[1] || ''
        const created = task({ ...input, id, state: 'pending' })
        if (created) tasks.set(created.id, created)
      } else if (block.name === 'TaskUpdate') {
        applyUpdate(tasks, input)
      } else {
        const rows = block.name === 'TaskList' ? listedTasks(output)
          : Array.isArray(input.todos) ? input.todos.map((row, index) => task(row, `todo-${index + 1}`))
            .filter((row): row is AgentPlanTask => Boolean(row)) : null
        if (rows) {
          tasks.clear()
          for (const row of rows) tasks.set(row.id, row)
        }
      }
    }
  }
  return [...tasks.values()]
}

/** Project only public task fields; task descriptions, metadata and tool payloads stay hidden. */
export function agentTaskPlanPresentation(trace?: AgentRuntimeTrace | null): AgentTaskPlan {
  const empty = { tasks: [], completedCount: 0, progress: 0 }
  if (!trace) return empty
  const calls = trace.messages.filter(message => message.role === 'assistant')
    .flatMap(message => message.content.filter((block): block is AgentToolCallBlock =>
      block.type === 'tool_call' && isTaskPlanTool(block.name)))
  // A persisted context can include tasks from an unrelated earlier turn, such as a greeting.
  if (!calls.length) return empty
  const snapshot = trace.tasksContext?.tasks
  const source = Array.isArray(snapshot)
    ? snapshot.map(row => task(row)).filter((row): row is AgentPlanTask => Boolean(row))
    : reconstructTasks(trace)
  const byId = new Map(source.map(row => [row.id, row]))
  const tasks = [...byId.values()].map(row => {
    const blockers = finishedStates.has(row.state) ? [] : row.blockedBy.filter(id =>
      !finishedStates.has(byId.get(id)?.state || '')).map(id => byId.get(id)?.subject || `任务 ${id}`)
    const stateLabel = ({ pending: '待处理', in_progress: trace.status === 'running' ? '进行中' : '待继续', completed: '已完成',
      skipped: '已跳过', failed: '执行失败', interrupted: '已停止' } as Record<string, string>)[row.state] || '状态待确认'
    return { ...row, blockers, stateLabel: blockers.length && row.state === 'pending' ? '等待前置任务' : stateLabel }
  })
  const completedCount = tasks.filter(row => finishedStates.has(row.state)).length
  return { tasks, completedCount, progress: tasks.length ? Math.round(completedCount * 100 / tasks.length) : 0 }
}
