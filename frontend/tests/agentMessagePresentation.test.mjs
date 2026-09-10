import { readFileSync } from 'node:fs'
import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'
import { h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import naiveUi from 'naive-ui'
import { activity, at, collaborationTrace, confirmationTrace, greetingTrace, member, message,
  metadata, pendingEntry, persistedExtra, runtimeHint, textBlock, toolCall, toolResult, trace } from './fixtures/agentConversation.mjs'

const server = await createServer({
  server: { middlewareMode: true, hmr: false }, appType: 'custom', logLevel: 'error',
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

test('完成后保留成员任务、调用记录和答复，隐藏原始参数与模型指标', async () => {
  const run = collaborationTrace()
  const html = await render(run)
  const positions = ['我先核对项目资料', '接着请资料助手', '已完成分类核对'].map(text => html.indexOf(text))
  assert.ok(positions.every((position, index) => position >= 0 && (!index || position > positions[index - 1])))
  assert.match(html, /读取项目基本信息/)
  assert.match(html, /协同处理任务/)
  assert.match(html, /检索知识库/)
  assert.match(html, /资料助手/)
  assert.match(html, /资料协同/)
  assert.match(html, /检查施工方案与验收资料的分类/)
  assert.doesNotMatch(html, /dobby_get_project|agent_invoke|agent_id|示例模型|调用详情/)
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

test('业务确认保留权威预览和版本，隐藏内部调用；旁观者无法确认', async () => {
  const run = confirmationTrace()
  const items = agentConversationItems(run)
  const step = items.find(item => item.kind === 'collaboration').step
  assert.equal(step.pending[0].reply_id, 'worker-reply')
  assert.equal(step.pending[0].event.tool_calls[0].confirmation_revision, 3)
  const html = await render(run)
  assert.match(html, /agent-business-confirmation/)
  assert.match(html, /修改前/)
  assert.match(html, /未分类/)
  assert.match(html, /确认本次操作/)
  assert.doesNotMatch(html, /dobby_update_document_classification|调用详情|record_id/)
  const spectator = await render(run, { canConfirm: false })
  assert.doesNotMatch(spectator, /<button|等待你确认后继续|需要你的确认/)
  assert.match(spectator, /等待请求发起人确认/)
})

test('缺少协同进度时，下级确认仍显示在对话中', async () => {
  const run = trace([message('root', [textBlock('已请资料助手处理')])], {
    status: 'awaiting_permission', subagentHitl: [pendingEntry()], turnFinishedAt: null,
  })
  const html = await render(run)
  assert.ok(html.indexOf('已请资料助手处理') < html.indexOf('本次业务变更'))
  assert.match(html, /确认本次操作/)
})

test('停止后不再保留可点击确认或伪装仍在运行', async () => {
  const run = confirmationTrace()
  run.status = 'interrupted'
  run.turnFinishedAt = at(4)
  const html = await render(run)
  assert.match(html, /已停止/)
  assert.doesNotMatch(html, /确认本次操作|等待确认|state-running/)
})

test('等待外部工具结果不能误报为等待用户确认', async () => {
  const run = confirmationTrace()
  run.status = 'awaiting_external_result'
  run.subagentHitl[0].event_type = 'require_external_execution'
  const html = await render(run)
  assert.match(html, /等待处理结果/)
  assert.doesNotMatch(html, /确认本次操作|等待请求发起人确认|等待确认/)
})

test('已收到结果时不能因残留 asking 状态再次请求确认', () => {
  assert.equal(toolPresentationState(toolCall('a', 'Write', {}, 'asking'), toolResult('a', 'Write'), true, false), 'success')
  assert.equal(toolPresentationState(toolCall('a', 'Write', {}, 'asking'), undefined, false, true), 'interrupted')
})

test('刷新后的历史记录与实时记录使用相同展示规则', async () => {
  const run = confirmationTrace()
  const restored = runtimeTraceFromExtraData(JSON.parse(JSON.stringify(persistedExtra(run))))
  const html = await render(restored)
  assert.match(html, /资料助手|本次业务变更|确认本次操作/)
  assert.doesNotMatch(html, /System|Runtime State|阶段耗时/)
})

test('群聊仅渲染一次智能体内容，确认和停止仍只对请求发起人开放', async () => {
  const run = confirmationTrace()
  const owner = await renderGroup(run, 7)
  assert.equal((owner.match(/我先核对项目资料/g) || []).length, 1)
  assert.match(owner, /确认本次操作|停止本次执行/)
  const spectator = await renderGroup(run, 8)
  assert.match(spectator, /等待请求发起人确认/)
  assert.doesNotMatch(spectator, /确认本次操作|停止本次执行/)
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

test('思考生成时自动展开，结束后收起但保留正文', async () => {
  const start = startThinking()
  const startHtml = await render(start)
  assert.equal(openThinkingCount(startHtml), 1)
  assert.match(startHtml, /Dobby 正在整理思路/)
  const delta = applyAgentRuntimeEvents(start, [thinkingEvent('THINKING_BLOCK_DELTA', 'thinking-1', { delta: '先核对项目资料。' })])
  assert.equal(openThinkingCount(await render(delta)), 1)
  const end = applyAgentRuntimeEvents(delta, [thinkingEvent('THINKING_BLOCK_END')])
  assert.equal(end.status, 'running')
  assert.equal(openThinkingCount(await render(end)), 0)
  assert.equal(delta.messages[0].content[0].state, 'streaming', '不能改动上一份流式快照')
  assert.match(await render(end), /先核对项目资料/)
})

test('多轮思考和调用按顺序保留，只有当前思考自动展开', async () => {
  const run = applyAgentRuntimeEvents(startThinking(), [
    thinkingEvent('THINKING_BLOCK_DELTA', 'thinking-1', { delta: '先查询项目。' }),
    thinkingEvent('THINKING_BLOCK_END'),
    thinkingEvent('TOOL_CALL_START', '', { tool_call_id: 'lookup', tool_call_name: 'Read', presentation: {label:'读取文件',source:'registration',category:'workspace'} }),
    thinkingEvent('THINKING_BLOCK_START', 'thinking-2'),
    thinkingEvent('THINKING_BLOCK_DELTA', 'thinking-2', { delta: '再核对查询结果。' }),
  ])
  const html = await render(run)
  assert.equal(openThinkingCount(html), 1)
  assert.equal((html.match(/class="agent-working"/g) || []).length, 1)
  const timeline = html.slice(html.indexOf('<details'))
  const positions = ['先查询项目', '读取文件', '再核对查询结果'].map(value => timeline.indexOf(value))
  assert.ok(positions.every((value, index) => value >= 0 && (!index || value > positions[index - 1])))
  assert.doesNotMatch(html, /调用详情/)
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

test('旧格式轮询恢复思考，后续答复使思考自动收起', async () => {
  const thinking = { type: 'thinking', id: 'old-thinking', thinking: '正在核对资料。' }
  const run = trace([{ ...message('old', [thinking]), finished_at: null }], { status: 'running', turnFinishedAt: null })
  assert.equal(openThinkingCount(await render(run)), 1)
  assert.match(await render(run), /正在核对资料/ )
  run.messages[0].content.push(textBlock('核对结果如下。'))
  assert.match(await render(run), /核对结果如下/)
  assert.equal(openThinkingCount(await render(run)), 0)
})


test('未知调用保留通用工作记录，隐藏函数与参数并保留思考和历史', async () => {
  const run = trace([message('private', [
    {type:'thinking',id:'reason',thinking:'先核对用户提供的信息'},
    toolCall('unknown','mcp__private__unknown',{password:'private-input'}),
    {...toolResult('unknown','mcp__private__unknown'),output:'private-output'},
    textBlock('已整理好你需要的信息。'),
  ])])
  const before=structuredClone(run)
  const html=await render(run)
  assert.doesNotMatch(html,/mcp__private|private-input|private-output|调用详情/)
  assert.match(html,/先核对用户提供的信息/)
  assert.match(html,/思考过程/)
  assert.match(html,/处理相关事项/)
  assert.match(html,/已整理好你需要的信息/)
  assert.deepEqual(run,before)
})

test('没有可展示结果或处理失败时不伪报成功，也不暴露错误堆栈', async () => {
  const run=trace([message('empty',[toolCall('x','internal_tool'),toolResult('x','internal_tool')])])
  assert.match(await render(run),/暂时没有可展示的结果/)
  run.status='error';run.messages[0].error={message:'Traceback secret-path'}
  const html=await render(run)
  assert.match(html,/处理遇到了问题/)
  assert.doesNotMatch(html,/Traceback|secret-path|已回复/)
})

test('缺少业务影响预览时拒绝按钮可用，确认执行不可用', async () => {
  const run=confirmationTrace()
  run.subagentHitl[0].event.tool_calls[0].confirmation_preview=null
  const html=await render(run)
  assert.match(html,/暂时无法展示这项操作的具体影响/)
  assert.match(html,/<button[^>]*class="allow"[^>]*disabled/)
  assert.doesNotMatch(html,/dobby_update_document_classification|record_id/)
})


test('停止过程中隐藏待确认按钮，只显示停止进度', async () => {
  const run=confirmationTrace();run.status='interrupting'
  const html=await render(run)
  assert.match(html,/正在停止处理/)
  assert.doesNotMatch(html,/确认本次操作|需要你的确认/)
})

test('最终正文中的表格和附件仍可展示', async () => {
  const run=trace([message('result',[
    textBlock('| 项目 | 状态 |\n| --- | --- |\n| 验收资料 | 已整理 |'),
    {type:'data',id:'image',name:'整理结果图',source:{type:'url',media_type:'image/png',url:'https://example.com/result.png'}},
  ])])
  const html=await render(run)
  assert.match(html,/<table>/)
  assert.match(html,/alt="整理结果图"/)
})


test('每次调用都保留独立记录，成功失败及缺失结果的历史状态真实', async () => {
  const run = trace([message('records', [
    toolCall('one','dobby_list_project_personnel',{secret:'hidden-person-id'}),
    toolResult('one','dobby_list_project_personnel'),
    toolCall('two','dobby_list_project_personnel',{secret:'hidden-person-id'}),
    toolResult('two','dobby_list_project_personnel',{},'error'),
    toolCall('three','dobby_list_project_tasks'),
  ])])
  const html = await render(run)
  assert.equal((html.match(/class="agent-work-record/g) || []).length, 3)
  assert.equal((html.match(/查看项目人员/g) || []).length, 2)
  assert.match(html,/已完成/)
  assert.match(html,/处理失败/)
  assert.match(html,/已结束/)
  assert.doesNotMatch(html,/dobby_list_project|hidden-person-id/)
  const restored = runtimeTraceFromExtraData(JSON.parse(JSON.stringify(persistedExtra(run))))
  assert.equal(await render(restored), html)
})


test('新工具和 MCP 使用事件文案；刷新及后续结果保留快照，不暴露调用标识', async () => {
  let run = applyAgentRuntimeEvents(null, [
    {type:'REPLY_START',reply_id:'new',created_at:at(0)},
    {type:'TOOL_CALL_START',reply_id:'new',tool_call_id:'new-call',tool_call_name:'mcp__new_server__never_seen',
      presentation:{label:'查询设备检修记录',source:'mcp_title',category:'mcp'},created_at:at(0)},
    {type:'TOOL_CALL_DELTA',reply_id:'new',tool_call_id:'new-call',delta:'{"sql":"private-query"}',created_at:at(0)},
  ])
  const running = await render(run)
  assert.match(running,/查询设备检修记录/)
  assert.doesNotMatch(running,/never_seen|new_server|private-query/)
  const before=structuredClone(run)
  run=applyAgentRuntimeEvents(run,[
    {type:'TOOL_RESULT_START',reply_id:'new',tool_call_id:'new-call',tool_call_name:'mcp__new_server__never_seen',created_at:at(1)},
    {type:'TOOL_RESULT_END',reply_id:'new',tool_call_id:'new-call',state:'success',created_at:at(2)},
    {type:'REPLY_END',reply_id:'new',finished_reason:'completed',created_at:at(3)},
  ])
  assert.equal(before.messages[0].content[0].presentation.label,'查询设备检修记录')
  const restored=runtimeTraceFromExtraData(JSON.parse(JSON.stringify(persistedExtra(run))))
  const html=await render(restored)
  assert.match(html,/查询设备检修记录/)
  assert.match(html,/已完成/)
  assert.doesNotMatch(html,/never_seen|new_server|private-query/)
})

test('协同工具复用服务端工作描述，旧记录没有描述时使用通用提示', async () => {
  const run=collaborationTrace()
  run.collaborations[0].activities[0].presentation={label:'核对设备清单',source:'database_catalog',category:'database'}
  const html=await render(run)
  assert.match(html,/核对设备清单/)
  assert.doesNotMatch(html,/weknora_search/)
  run.messages[0].content.find(block=>block.type==='tool_call').presentation=null
  assert.match(await render(run),/处理相关事项/)
})


test('冷启动历史接口返回的记忆记录直接显示具体描述', async () => {
  const history = JSON.parse(readFileSync(new URL('./fixtures/cold-memory-history.json', import.meta.url), 'utf8'))
  const html = await render(trace(history.messages))
  assert.equal((html.match(/class="agent-work-record/g) || []).length, 6)
  assert.equal((html.match(/回顾相关信息/g) || []).length, 4)
  assert.equal((html.match(/记下重要信息/g) || []).length, 2)
  assert.match(html,/回顾相关信息/)
  assert.doesNotMatch(html,/处理相关事项|do-not-display|search_memory|add_memory|memory_write/)
})
