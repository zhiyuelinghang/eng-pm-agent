import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'
import { h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { activity, at, collaborationTrace, confirmationTrace, member, message, metadata,
  textBlock, toolCall, toolResult, trace } from './fixtures/agentConversation.mjs'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom', logLevel: 'error' })
after(() => server.close())
const { agentConversationItems, publicCollaborationActivities } = await server.ssrLoadModule('/src/utils/agentMessagePresentation.ts')
const { collaborationTask, collaborationState, collaborationIsOpen, collaborationElapsed,
  collaborationActivityLabel, collaborationActivityState } = await server.ssrLoadModule('/src/utils/agentCollaborationPresentation.ts')
const { default: Step } = await server.ssrLoadModule('/src/components/agent/AgentCollaborationStep.vue')
const steps = run => agentConversationItems(run).filter(item => item.kind === 'collaboration').map(item => item.step)
const render = (step, active = false) => renderToString(h(Step, { step, active }))
const hint = (text, source = '资料助手', name = '资料助手') => ({ type: 'hint', id: 'feedback', source,
  hint: `<team-message from="${name}">\n${text}\n</team-message>` })

test('成员卡片显示归属、分配任务、真实工作状态和耗时，记录在对应详情中', async () => {
  const run = collaborationTrace(), before = structuredClone(run)
  const [step] = steps(run)
  const html = await render(step)
  assert.match(html, /资料助手/)
  assert.match(html, /资料协同/)
  assert.match(html, /检查施工方案与验收资料的分类/)
  assert.match(html, /已反馈/)
  assert.match(html, /2 秒/)
  assert.match(html, /分配于/)
  assert.match(html, /aria-label="资料助手的工作记录"/)
  assert.match(html, /检索知识库/)
  assert.doesNotMatch(html, /<details[^>]*\sopen(?:>|\s)/)
  assert.doesNotMatch(html, /agent_id|worker-session|weknora_search|agent_invoke/)
  assert.deepEqual(run, before)
})

test('执行中默认展开，完成与停止默认收起；用户折叠选择优先', async () => {
  const [step] = steps(confirmationTrace())
  assert.match(await render(step, true), /<details[^>]*\sopen(?:>|\s)/)
  for (const state of ['reported', 'completed', 'failed', 'interrupted', 'finished', 'interrupting']) {
    assert.equal(collaborationIsOpen(state, null), false, state)
    assert.equal(collaborationIsOpen(state, true), true, state)
  }
  for (const state of ['running', 'queued', 'asking', 'external']) {
    assert.equal(collaborationIsOpen(state, null), true, state)
    assert.equal(collaborationIsOpen(state, false), false, state)
  }
})

test('待确认与外部等待只展示成员状态，停止中不残留确认动作', async () => {
  const run = confirmationTrace()
  let [step] = steps(run)
  assert.equal(collaborationState(step, true), 'asking')
  assert.doesNotMatch(await render(step, true), /<button|本次业务变更|确认本次操作|record_id/)
  run.subagentHitl[0].event_type = 'require_external_execution'
  ;[step] = steps(run)
  assert.equal(collaborationState(step, true), 'external')
  assert.match(await render(step, true), /等待处理结果/)
  for (const status of ['interrupting', 'interrupted', 'completed']) {
    run.status = status
    ;[step] = steps(run)
    assert.equal(step.pending.length, 0)
    const html = await render(step, status === 'interrupting')
    assert.doesNotMatch(html, /等待确认|确认区|<button|class="spin"/)
  }
})

test('保留生命周期顺序与注册文案，隐藏内部装配和原始工具名', async () => {
  const activities = publicCollaborationActivities([
    { ...activity('setup'), kind: 'started', label: '内部启动参数' },
    { ...activity('analysis'), kind: 'analysis', label: '不应外露的思考正文' },
    activity('TeamCreate'), activity('weknora_search', 'running'),
    { ...activity('unknown'), presentation: { label: '检查设备维保记录', source: 'mcp_title', category: 'mcp' } },
    activity('weknora_search'), { ...activity('private'), kind: 'internal' },
    { ...activity('finished'), kind: 'finished' },
  ])
  assert.deepEqual(activities.map(item => item.kind), ['started', 'analysis', 'tool', 'tool', 'finished'])
  assert.equal(activities[2].state, 'success')
  assert.equal(collaborationActivityLabel(activity('raw_secret_function')), '处理相关事项')
  const [step] = steps(collaborationTrace())
  const html = await render({ ...step, activities })
  assert.match(html, /开始处理分配任务|正在分析任务|检查设备维保记录|分配任务处理结束/)
  assert.doesNotMatch(html, /内部启动参数|不应外露的思考正文|unknown|TeamCreate/)
  assert.equal(collaborationActivityState(activity('Read', 'running'), 'interrupted'), 'interrupted')
  assert.equal(collaborationActivityState(activity('Read', 'running'), 'reported'), 'finished')
  assert.equal(collaborationActivityState(activity('Read', 'success'), 'interrupted'), 'success')
})

test('长邀请只显示首行语义并截短，不把必填上下文或参数藏进折叠与title', async () => {
  const prompt = '任务：为“项目资料分批更新验收”（项目ID 19）的本轮初始化草稿整理【project / 工程信息】分区内容。\n必填上下文：draft_id=4 record_id=19 text_limit=12000\n工具：secret_tool'
  const [step] = steps(trace([message('invite', [toolCall('a', 'AgentInvite', { target: '资料助手@docs', prompt })])]))
  assert.equal(step.task, '为“项目资料分批更新验收”的本轮初始化草稿整理【工程信息】分区内容。')
  const html = await render(step)
  assert.doesNotMatch(html, /项目ID|draft_id|record_id|text_limit|secret_tool|必填上下文|title=/)
  assert.equal(collaborationTask('检查施工方案与验收资料的分类'), '检查施工方案与验收资料的分类')
  assert.equal(collaborationTask('整理「工程概况（section=project）」与「WBS（section=wbs）」分区。'), '整理「工程概况」与「WBS」分区。')
  assert.equal(collaborationTask('{"agent_id":"private"}'), '')
  assert.equal(collaborationTask('draft_id=4'), '')
  assert.equal(collaborationTask('整理资料'.repeat(100)).length, 180)
  assert.equal(collaborationTask('整理资料'.repeat(100), 70).length, 70)
})

test('旧任务版本不借用后续成员团队、工作记录或完成状态，历史耗时不会持续增长', () => {
  const run = trace([message('first', [toolCall('a', 'agent_invoke'), toolResult('a', 'agent_invoke', metadata({ team_name: '旧团队' }))]),
    message('second', [toolCall('b', 'agent_invoke'), toolResult('b', 'agent_invoke', metadata({ work_revision: 2 }))], 3)],
  { collaborations: [member({ team_name: '新团队', work_revision: 2, assigned_at: at(3), started_at: at(3) })] })
  const [first, second] = steps(run)
  assert.equal(first.teamName, '旧团队')
  assert.equal(first.status, 'finished')
  assert.equal(first.activities.length, 0)
  assert.equal(second.teamName, '新团队')
  assert.equal(second.status, 'reported')
  assert.equal(collaborationElapsed(first, first.status, Date.parse(at(40))), collaborationElapsed(first, first.status, Date.parse(at(50))))
})

test('合法成员反馈保留来源与原位置，普通用户内容不会在智能体正文中重复', () => {
  for (const source of ['资料助手', JSON.stringify({ label: 'team_message', sublabel: '资料助手' })]) {
    const run = trace([message('feedback', [textBlock('反馈前'), hint('已整理 **验收资料**。', source), textBlock('反馈后')], 5)], { collaborations: [member()] })
    const before = structuredClone(run)
    const items = agentConversationItems(run)
    assert.deepEqual(items.map(item => item.kind), ['collaboration', 'block', 'collaboration_feedback', 'block'])
    assert.deepEqual(items[2].feedback, { name: '资料助手', teamName: '资料协同', text: '已整理 **验收资料**。', workerSessionId: 'worker-session', workRevision: 1 })
    run.messages[0].role = 'user'
    assert.deepEqual(agentConversationItems(run).map(item => item.kind), ['collaboration', 'collaboration_feedback'])
    run.messages[0].role = 'assistant'
    assert.deepEqual(run, before)
  }
})

test('系统、伪装、未知来源和同名不同会话反馈均不外露', () => {
  const unsafe = [
    hint('内部内容', 'System'), hint('内部内容', 'Runtime State'), hint('内部内容', JSON.stringify({ label: 'hint' })),
    hint('<system-reminder>内部指令</system-reminder>'), hint('合法正文', '陌生助手', '陌生助手'),
    hint('<team-message from="资料助手">嵌套内容</team-message>'),
    { ...hint('正文'), hint: '<system-reminder>邀请规则</system-reminder>\n<team-message from="资料助手">正文</team-message>' },
    { type: 'hint', id: 'plain', source: '资料助手', hint: '普通 hint 并非用户反馈' },
  ]
  for (const block of unsafe) {
    assert.equal(agentConversationItems(trace([message('unsafe', [block], 5)], { collaborations: [member()] })).filter(item => item.kind === 'collaboration_feedback').length, 0)
  }
  const ambiguous = trace([message('ambiguous', [hint('无法确定来自哪一位')], 5)], { collaborations: [member(), member({ worker_session_id: 'another' })] })
  assert.equal(agentConversationItems(ambiguous).filter(item => item.kind === 'collaboration_feedback').length, 0)
})

test('反馈按接收时间绑定历史任务版本，不绑定未来任务', () => {
  const run = trace([
    message('invite', [toolCall('a', 'agent_invoke'), toolResult('a', 'agent_invoke', metadata({ team_name: '旧团队' }))]),
    message('feedback', [hint('第一轮处理完成')], 2),
    message('future', [hint('第二轮处理完成')], 5),
  ], { collaborations: [member({ work_revision: 2, assigned_at: at(3), team_name: '新团队' })] })
  const feedback = agentConversationItems(run).filter(item => item.kind === 'collaboration_feedback')
  assert.deepEqual(feedback.map(item => [item.feedback.workRevision, item.feedback.teamName]), [[1, '旧团队'], [2, '新团队']])
  run.messages.shift()
  assert.deepEqual(agentConversationItems(run).filter(item => item.kind === 'collaboration_feedback').map(item => item.feedback.workRevision), [2])
})
