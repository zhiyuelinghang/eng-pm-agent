import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'
import { h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import naiveUi from 'naive-ui'
import { activity, at, collaborationTrace, confirmationTrace, greetingTrace, member, message,
  metadata, pendingEntry, persistedExtra, runtimeHint, textBlock, toolCall, toolResult, trace } from './fixtures/agentConversation.mjs'

const server = await createServer({
  server: { middlewareMode: true }, appType: 'custom', logLevel: 'error',
  plugins: [{
    name: 'presentation-test-chat-api', enforce: 'pre',
    resolveId(id) {
      if (id === '@/api/projectChat' || /\/src\/api\/projectChat(?:\.ts)?$/.test(id.replaceAll('\\', '/'))) return '\0test-chat-api'
    },
    load(id) {
      if (id === '\0test-chat-api') return `
        export const confirmProjectChatAgentTool = () => { throw new Error('展示测试禁止调用业务 API') }
        export const stopProjectChatAgentRun = () => { throw new Error('展示测试禁止调用业务 API') }
      `
    },
  }],
})
const { NMessageProvider } = naiveUi
after(() => server.close())
const { agentConversationItems, publicToolActivities, toolPresentationState } = await server.ssrLoadModule('/src/utils/agentMessagePresentation.ts')
const { runtimeTraceFromExtraData, applyAgentRuntimeEvents } = await server.ssrLoadModule('/src/types/agentRuntime.ts')
const { agentToolLabel } = await server.ssrLoadModule('/src/utils/agentRuntimeLabels.ts')
const { default: MessageContent } = await server.ssrLoadModule('/src/components/agent/AgentMessageContent.vue')
const { default: ChatRun } = await server.ssrLoadModule('/src/components/chat/ChatAgentRunControls.vue')
const render = (run, props = {}) => renderToString(h(MessageContent, { runtimeTrace: run, ...props }))
const groupItem = run => ({ id: 1, sender_type: 'agent', message_type: 'agent', content: '@Dobby 正在校验调用授权…', metadata: persistedExtra(run) })
const renderGroup = (run, currentUserId) => renderToString(h(NMessageProvider, null, {
  default: () => h(ChatRun, { item: groupItem(run), currentUserId }),
}))

test('普通问候隐藏系统提示、内部阶段和内部计划，保留答复且不修改原始记录', async () => {
  const run = greetingTrace()
  const before = structuredClone(run)
  const html = await render(run)
  assert.match(html, /你好！我是 Dobby/)
  for (const internal of ['System', 'Runtime State', '内部上下文', '系统正文', '平台鉴权', 'AgentScope', '内部计划', '阶段耗时', '运行阶段']) {
    assert.ok(!html.includes(internal), internal)
  }
  assert.equal((html.match(/agent-runtime-footer/g) || []).length, 1)
  assert.deepEqual(run, before)
})

test('仅内部事件不会产生空卡片或已完成提示，运行中仍有简洁 loading', async () => {
  const run = trace([message('internal', [runtimeHint])], { status: 'running', turnFinishedAt: null })
  const html = await render(run)
  assert.match(html, /正在处理请求/)
  assert.doesNotMatch(html, /agent-runtime-footer|已完成|agent-hint|运行阶段/)
  assert.equal(agentConversationItems(run).length, 0)
})

test('工具、协同和答复按实际调用位置展示，协同默认收起', async () => {
  const html = await render(collaborationTrace())
  const positions = ['我先核对项目资料', '读取项目基本信息', '接着请资料助手', 'agent-collaboration-step', '已完成分类核对'].map(text => html.indexOf(text))
  assert.ok(positions.every((position, index) => position >= 0 && (!index || position > positions[index - 1])))
  assert.match(html, /检查施工方案与验收资料的分类/)
  assert.match(html, /检索知识库已完成/)
  assert.doesNotMatch(html, /agent-collaboration-step[^>]*\sopen(?:>|\s)/)
  assert.doesNotMatch(html, /agent-tool[^>]*\sopen(?:>|\s)/)
})

test('旧 AgentInvite 也按各自位置展示，不把一条消息中的协同挪到开头', () => {
  const items = agentConversationItems(trace([message('legacy', [
    toolCall('a', 'AgentInvite', { target: '资料助手@docs', prompt: '整理资料' }), textBlock('然后分析风险'),
    toolCall('b', 'AgentInvite', { target: '风险助手@risk', prompt: '分析风险' }),
  ])]))
  assert.deepEqual(items.map(item => item.kind), ['collaboration', 'block', 'collaboration'])
  assert.equal(items[0].step.name, '资料助手')
  assert.equal(items[2].step.name, '风险助手')
})

test('已派发不等于已完成；后续任务版本的记录不会串入前次协同', () => {
  const run = trace([message('rounds', [
    toolCall('a', 'agent_invoke'), toolResult('a', 'agent_invoke', metadata()),
    toolCall('b', 'agent_invoke'), toolResult('b', 'agent_invoke', metadata({ work_revision: 2 })),
  ])], { collaborations: [member({ work_revision: 2, activities: [activity('Write')] })] })
  const items = agentConversationItems(run)
  assert.equal(items[0].step.status, 'finished')
  assert.equal(items[0].step.activities.length, 0)
  assert.equal(items[1].step.status, 'reported')
  assert.equal(items[1].step.activities[0].tool_name, 'Write')
  const dispatch = agentConversationItems(trace([message('a', [toolCall('a', 'agent_invoke'), toolResult('a', 'agent_invoke')])]))
  assert.equal(dispatch[0].step.status, 'finished')
})

test('嵌套协同按分配时间插入前后答复之间', () => {
  const items = agentConversationItems(trace([
    message('start', [textBlock('开始处理')]), message('final', [textBlock('最终结果')], 5),
  ], { collaborations: [member()] }))
  assert.deepEqual(items.map(item => item.kind), ['block', 'collaboration', 'block'])
})

test('协同工作记录隐藏装配活动，合并同一次工具的开始和完成', () => {
  const records = publicToolActivities([
    { ...activity('setup'), kind: 'started', label: '内部启动阶段' }, activity('TeamCreate'),
    activity('weknora_search', 'running'), activity('weknora_search'),
  ])
  assert.equal(records.length, 1)
  assert.equal(records[0].state, 'success')
})

test('确认内联在对应协同下，完整保留权威预览和版本；旁观者无法确认', async () => {
  const run = confirmationTrace()
  const items = agentConversationItems(run)
  const step = items.find(item => item.kind === 'collaboration').step
  assert.equal(step.pending[0].reply_id, 'worker-reply')
  assert.equal(step.pending[0].event.tool_calls[0].confirmation_revision, 3)
  const html = await render(run)
  assert.ok(html.indexOf('agent-collaboration-step') < html.indexOf('本次业务变更'))
  assert.match(html, /修改前/)
  assert.match(html, /未分类/)
  assert.match(html, /允许本次/)
  assert.match(html, /agent-collaboration-step[^>]*\sopen/)
  const spectator = await render(run, { canConfirm: false })
  assert.doesNotMatch(spectator, /<button/)
  assert.match(spectator, /等待请求发起人确认/)
})

test('缺少协同进度时，下级确认仍显示在对话中', async () => {
  const run = trace([message('root', [textBlock('已请资料助手处理')])], {
    status: 'awaiting_permission', subagentHitl: [pendingEntry()], turnFinishedAt: null,
  })
  const html = await render(run)
  assert.ok(html.indexOf('已请资料助手处理') < html.indexOf('本次业务变更'))
  assert.match(html, /允许本次/)
})

test('停止后不再保留可点击确认或伪装仍在运行', async () => {
  const run = confirmationTrace()
  run.status = 'interrupted'
  run.turnFinishedAt = at(4)
  const html = await render(run)
  assert.match(html, /已停止/)
  assert.doesNotMatch(html, /允许本次|等待确认|state-running/)
})

test('等待外部工具结果不能误报为等待用户确认', async () => {
  const run = confirmationTrace()
  run.status = 'awaiting_external_result'
  run.subagentHitl[0].event_type = 'require_external_execution'
  const html = await render(run)
  assert.match(html, /等待结果/)
  assert.doesNotMatch(html, /允许本次|等待请求发起人确认|等待确认/)
})

test('已收到结果时不能因残留 asking 状态再次请求确认', () => {
  assert.equal(toolPresentationState(toolCall('a', 'Write', {}, 'asking'), toolResult('a', 'Write'), true, false), 'success')
  assert.equal(toolPresentationState(toolCall('a', 'Write', {}, 'asking'), undefined, false, true), 'interrupted')
})

test('刷新后的历史记录与实时记录使用相同展示规则', async () => {
  const run = confirmationTrace()
  const restored = runtimeTraceFromExtraData(JSON.parse(JSON.stringify(persistedExtra(run))))
  const html = await render(restored)
  assert.match(html, /资料助手|本次业务变更|允许本次/)
  assert.doesNotMatch(html, /System|Runtime State|阶段耗时/)
})

test('群聊仅渲染一次智能体内容，确认和停止仍只对请求发起人开放', async () => {
  const run = confirmationTrace()
  const owner = await renderGroup(run, 7)
  assert.equal((owner.match(/我先核对项目资料/g) || []).length, 1)
  assert.match(owner, /允许本次|停止本次执行/)
  const spectator = await renderGroup(run, 8)
  assert.match(spectator, /等待请求发起人确认/)
  assert.doesNotMatch(spectator, /允许本次|停止本次执行/)
})

test('群聊启动占位不展示授权检查文案', async () => {
  const html = await renderGroup(trace([message('init', [])], { status: 'running', turnFinishedAt: null }), 7)
  assert.match(html, /正在处理请求/)
  assert.doesNotMatch(html, /校验调用授权|运行阶段/)
})

test('搜索与未知工具显示真实操作名称', () => {
  assert.equal(agentToolLabel('agent_search'), '查找协同智能体')
  assert.equal(agentToolLabel('memory_search'), '检索记忆')
  assert.equal(agentToolLabel('mcp__business__search_contracts'), 'search_contracts')
})

const thinkingEvent = (type, blockId = 'thinking-1', extra = {}) => ({
  type, reply_id: 'thinking-reply', block_id: blockId, created_at: at(0), ...extra,
})
const startThinking = () => applyAgentRuntimeEvents(null, [
  thinkingEvent('REPLY_START'), thinkingEvent('THINKING_BLOCK_START'),
])
const openThinkingCount = html => (html.match(/<details[^>]*class="agent-thinking"[^>]*\sopen(?:>|\s)/g) || []).length

test('每段思考开始即展开，结束事件立即收起，无需等待回复结束', async () => {
  const start = startThinking()
  const startHtml = await render(start)
  assert.equal(openThinkingCount(startHtml), 1)
  assert.match(startHtml, /正在思考/)
  const delta = applyAgentRuntimeEvents(start, [thinkingEvent('THINKING_BLOCK_DELTA', 'thinking-1', { delta: '先核对项目资料。' })])
  assert.equal(openThinkingCount(await render(delta)), 1)
  const end = applyAgentRuntimeEvents(delta, [thinkingEvent('THINKING_BLOCK_END')])
  assert.equal(end.status, 'running')
  assert.equal(openThinkingCount(await render(end)), 0)
  assert.equal(delta.messages[0].content[0].state, 'streaming', '不能改动上一份流式快照')
  assert.match(await render(end), /先核对项目资料/)
})

test('工具调用之后的新思考独立展开，前段保持收起', async () => {
  const run = applyAgentRuntimeEvents(startThinking(), [
    thinkingEvent('THINKING_BLOCK_DELTA', 'thinking-1', { delta: '先查询项目。' }),
    thinkingEvent('THINKING_BLOCK_END'),
    thinkingEvent('TOOL_CALL_START', '', { tool_call_id: 'lookup', tool_call_name: 'Read' }),
    thinkingEvent('THINKING_BLOCK_START', 'thinking-2'),
    thinkingEvent('THINKING_BLOCK_DELTA', 'thinking-2', { delta: '再核对查询结果。' }),
  ])
  const html = await render(run)
  assert.equal(openThinkingCount(html), 1)
  const blocks = html.match(/<details[^>]*class="agent-thinking"[^>]*>/g)
  assert.doesNotMatch(blocks[0], /\sopen/)
  assert.match(blocks[1], /\sopen/)
})

test('模型结束或回复结束会兜底收起缺少结束事件的思考', async () => {
  for (const eventType of ['MODEL_CALL_END', 'REPLY_END']) {
    const run = applyAgentRuntimeEvents(startThinking(), [thinkingEvent('THINKING_BLOCK_DELTA', 'thinking-1', { delta: '正在核对。' }), thinkingEvent(eventType)])
    assert.equal(openThinkingCount(await render(run)), 0)
    assert.equal(run.messages[0].content[0].state, 'finished')
  }
})

test('停止、等待确认、协同等待及历史记录不自动展开', async () => {
  for (const status of ['interrupted', 'interrupting', 'awaiting_permission', 'awaiting_external_result', 'completed']) {
    const run = startThinking()
    run.status = status
    assert.equal(openThinkingCount(await render(run)), 0, status)
  }
  const waiting = applyAgentRuntimeEvents(startThinking(), [thinkingEvent('REPLY_END', '', { platform_collaboration_pending: true })])
  assert.equal(waiting.status, 'running')
  assert.equal(openThinkingCount(await render(waiting)), 0)
})

test('旧格式轮询只展开当前末段思考，正文或工具已出现则收起', async () => {
  const thinking = { type: 'thinking', id: 'old-thinking', thinking: '正在核对资料。' }
  const run = trace([{ ...message('old', [thinking]), finished_at: null }], { status: 'running', turnFinishedAt: null })
  assert.equal(openThinkingCount(await render(run)), 1)
  run.messages[0].content.push(textBlock('核对结果如下。'))
  assert.equal(openThinkingCount(await render(run)), 0)
})
