import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'
import { h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { message, trace, toolCall, toolResult, persistedExtra, greetingTrace } from './fixtures/agentConversation.mjs'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom', logLevel: 'error' })
after(() => server.close())
const { agentTaskPlanPresentation: present, isTaskPlanTool } = await server.ssrLoadModule('/src/utils/agentTaskPlanPresentation.ts')
const { default: TaskPlan } = await server.ssrLoadModule('/src/components/agent/AgentTaskPlan.vue')
const { default: MessageContent } = await server.ssrLoadModule('/src/components/agent/AgentMessageContent.vue')
const { applyAgentRuntimeEvents, runtimeTraceFromExtraData } = await server.ssrLoadModule('/src/types/agentRuntime.ts')
const render = run => renderToString(h(TaskPlan, { runtimeTrace: run }))
const result = (id, name, output, state = 'success') => ({ ...toolResult(id, name, {}, state), output })
const create = (id, subject, callId = `create-${id}`) => [
  toolCall(callId, 'TaskCreate', { subject, description: '内部执行参数不得外露', metadata: { secret: '不展示的值' } }),
  result(callId, 'TaskCreate', [{ type: 'text', id: `text-${id}`, text: `Task (id=${id}) created successfully: ${subject}` }]),
]
const update = (id, input, callId = `update-${id}`) => [
  toolCall(callId, 'TaskUpdate', { task_id: String(id), ...input }),
  result(callId, 'TaskUpdate', `Update task (id=${id}) status.`),
]

test('真实 22/24 的五项计划模式读取完整持久化快照，仅呈现安全任务字段', async () => {
  const subjects = ['理解本轮资料与实际涉及分区', '读取正式现状与本会话草稿', '创建本轮初始化草稿并邀请工程信息专家', '核对分区落库并提交核验', '等待用户确认草稿']
  const run = trace([message('plan', subjects.flatMap((subject, index) => create(String(index + 1), subject)))], {
    tasksContext: { tasks: subjects.map((subject, index) => ({ id: String(index + 1), subject,
      state: index < 4 ? 'completed' : 'in_progress', description: '内部执行参数不得外露', metadata: { secret: '不展示的值' } })) },
  })
  const before = structuredClone(run)
  const plan = present(runtimeTraceFromExtraData(persistedExtra(run)))
  assert.equal(plan.tasks.length, 5)
  assert.equal(plan.completedCount, 4)
  assert.equal(plan.progress, 80)
  const html = await render(run)
  for (const subject of subjects) assert.ok(html.includes(subject), subject)
  assert.match(html, /4 \/ 5/)
  assert.match(html, /aria-valuenow="4"/)
  assert.match(html, /待继续/)
  assert.doesNotMatch(html, /内部执行参数|不展示的值|TaskCreate|TaskUpdate|metadata/)
  assert.deepEqual(run, before)
})

test('只有普通问候和无关上下文时不展示之前的计划', async () => {
  assert.equal(present(greetingTrace()).tasks.length, 0)
  assert.doesNotMatch(await render(greetingTrace()), /执行计划|内部计划/)
  assert.equal(present(null).tasks.length, 0)
})

test('流式 state_updated 按 id 更新同一行，后续任务事件不重复追加', () => {
  const run = trace([message('plan', [...create('1', '核对资料'), ...create('2', '生成草稿')])], { status: 'running' })
  const withState = applyAgentRuntimeEvents(run, [{ type: 'CUSTOM', name: 'state_updated', value: {
    tasks_context: { tasks: [{ id: '1', subject: '核对资料', state: 'completed' }, { id: '2', subject: '生成草稿', state: 'in_progress' }] },
  } }])
  assert.deepEqual(present(withState).tasks.map(task => [task.id, task.state]), [['1', 'completed'], ['2', 'in_progress']])
  const completed = applyAgentRuntimeEvents(withState, [{ type: 'CUSTOM', name: 'state_updated', value: {
    tasks_context: { tasks: [{ id: '1', subject: '核对资料', state: 'completed' }, { id: '2', subject: '生成草稿', state: 'completed' }] },
  } }])
  assert.equal(present(completed).tasks.length, 2)
  assert.equal(present(completed).progress, 100)
  assert.equal(present(run).progress, 0)
})

test('旧历史缺少快照仍从成功 TaskCreate/TaskUpdate 还原；工具输出不是任务状态', () => {
  const run = trace([message('plan', [...create('1', '核对资料'), ...create('2', '生成草稿'),
    ...update('1', { status: 'completed' }), ...update('2', { status: 'in_progress' })])])
  const plan = present(run)
  assert.deepEqual(plan.tasks.map(task => [task.id, task.state]), [['1', 'completed'], ['2', 'in_progress']])
  assert.equal(plan.progress, 50)
})

test('快照是权威状态，不用旧调用覆盖较新的任务完成与删除', () => {
  const messages = [message('plan', [...create('1', '核对资料'), ...update('1', { status: 'in_progress' })])]
  assert.equal(present(trace(messages, { tasksContext: { tasks: [{ id: '1', subject: '核对资料', state: 'completed' }] } })).progress, 100)
  assert.equal(present(trace(messages, { tasksContext: { tasks: [] } })).tasks.length, 0)
})

test('失败、拒绝和未完成工具不会把待办改成已完成或新增虚假任务', () => {
  const blocks = [...create('1', '核对资料'), toolCall('pending', 'TaskCreate', { subject: '尚未建立' }),
    toolCall('failure', 'TaskCreate', { subject: '建立失败' }), result('failure', 'TaskCreate', '错误', 'error'),
    toolCall('denied', 'TaskUpdate', { task_id: '1', status: 'completed' }), result('denied', 'TaskUpdate', '拒绝', 'denied')]
  const plan = present(trace([message('plan', blocks)]))
  assert.equal(plan.tasks.length, 1)
  assert.equal(plan.tasks[0].state, 'pending')
})

test('负责人及阻塞依赖可见，前置完成后不再显示过期阻塞', async () => {
  const run = trace([message('plan', [...create('1', '核对资料'), ...create('2', '生成草稿'),
    ...update('2', { owner: '工程信息助手', add_blocked_by: ['1'] })])])
  assert.deepEqual(present(run).tasks[1].blockers, ['核对资料'])
  const html = await render(run)
  assert.match(html, /负责人：工程信息助手/)
  assert.match(html, /等待：核对资料/)
  assert.match(html, /等待前置任务/)
  run.messages.push(message('finished', update('1', { status: 'completed' })))
  assert.deepEqual(present(run).tasks[1].blockers, [])
})

test('TaskUpdate add_blocks 及删除使用对应任务 id，保持其他任务顺序', () => {
  const run = trace([message('plan', [...create('1', '核对资料'), ...create('2', '生成草稿'), ...create('3', '用户确认'),
    ...update('1', { add_blocks: ['2'] })])])
  assert.deepEqual(present(run).tasks[1].blockers, ['核对资料'])
  run.messages.push(message('delete', update('1', { status: 'deleted' })))
  assert.deepEqual(present(run).tasks.map(task => task.id), ['2', '3'])
  assert.deepEqual(present(run).tasks[0].blockers, [])
})

test('TaskList 的真实文本格式和空列表可独立恢复当前计划', () => {
  const run = trace([message('list', [toolCall('list', 'TaskList'), result('list', 'TaskList',
    '1 [in_progress] 核对资料(资料助手)\n2 [pending] 生成草稿[blocked by 1]')])])
  assert.equal(present(run).tasks[0].owner, '资料助手')
  assert.deepEqual(present(run).tasks[1].blockers, ['核对资料'])
  run.messages.push(message('empty', [toolCall('empty', 'TaskList'), result('empty', 'TaskList', 'No tasks available.')]))
  assert.equal(present(run).tasks.length, 0)
})

test('兼容 TodoWrite 全量替换，状态更新维持稳定行而非追加记录', () => {
  const run = trace([message('todo', [toolCall('todo', 'TodoWrite', { todos: [{ content: '核对资料', status: 'pending' }] }),
    result('todo', 'TodoWrite', 'Todos updated')])])
  const oldId = present(run).tasks[0].id
  run.messages.push(message('todo-done', [toolCall('done', 'TodoWrite', { todos: [{ content: '核对资料', status: 'completed' }] }),
    result('done', 'TodoWrite', 'Todos updated')]))
  assert.equal(present(run).tasks.length, 1)
  assert.equal(present(run).tasks[0].id, oldId)
  assert.equal(present(run).progress, 100)
  assert.equal(isTaskPlanTool('TodoWrite'), true)
  assert.equal(isTaskPlanTool('TeamCreate'), false)
})

test('保持可折叠的完整列表和已完成进度，不因回合结束隐藏或擅自完成待办', async () => {
  const run = trace([message('plan', [...create('1', '<script>unsafe</script>'), ...update('1', { status: 'completed' })])])
  const html = await render(run)
  assert.match(html, /<details[^>]*open/)
  assert.match(html, /<summary/)
  assert.match(html, /&lt;script&gt;unsafe&lt;\/script&gt;/)
  assert.doesNotMatch(html, /<script>unsafe/)
  assert.match(html, /1 \/ 1/)
  const pending = present(trace([message('waiting', create('5', '等待用户确认草稿'))]))
  assert.equal(pending.tasks[0].state, 'pending')
})

test('真实 22/24 末项待用户确认及停止中的计划不持续转圈，也不伪造完成', async () => {
  const run = trace([message('waiting', [...create('5', '等待用户确认草稿'), ...update('5', { status: 'in_progress' })])])
  for (const status of ['completed', 'interrupted', 'interrupting', 'awaiting_permission']) {
    run.status = status
    const plan = present(run)
    assert.equal(plan.tasks[0].state, 'in_progress')
    assert.equal(plan.tasks[0].stateLabel, '待继续')
    assert.equal(plan.completedCount, 0)
    const html = await render(run)
    assert.doesNotMatch(html, /class="spin"|进行中/)
    assert.match(html, /待继续/)
  }
  run.status = 'running'
  assert.match(await render(run), /class="spin"/)
  assert.equal(present(run).tasks[0].stateLabel, '进行中')
})

test('完整用户消息必须接入结构化计划，历史加载后仍保留全部待办与进度', async () => {
  const run = trace([message('plan', [...create('1', '核对资料'), ...create('2', '等待用户确认草稿'),
    ...update('1', { status: 'completed' }), ...update('2', { status: 'in_progress' })])])
  const restored = runtimeTraceFromExtraData(persistedExtra(run))
  const html = await renderToString(h(MessageContent, { runtimeTrace: restored }))
  assert.match(html, /class="agent-task-plan"/)
  assert.match(html, /执行计划/)
  assert.match(html, /data-task-id="1"/)
  assert.match(html, /data-task-id="2"/)
  assert.match(html, /核对资料/)
  assert.match(html, /等待用户确认草稿/)
  assert.match(html, /1 \/ 2/)
  assert.match(html, /待继续/)
  assert.doesNotMatch(html, /内部执行参数不得外露/)
})
