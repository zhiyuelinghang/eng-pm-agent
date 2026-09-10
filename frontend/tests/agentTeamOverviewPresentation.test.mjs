import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'
import { h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { activity, at, member, message, trace, toolCall, toolResult, persistedExtra } from './fixtures/agentConversation.mjs'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom', logLevel: 'error' })
after(() => server.close())
const { agentTeamOverviewPresentation: present } = await server.ssrLoadModule('/src/utils/agentTeamOverviewPresentation.ts')
const { default: Overview } = await server.ssrLoadModule('/src/components/agent/AgentTeamOverview.vue')
const { default: MessageContent } = await server.ssrLoadModule('/src/components/agent/AgentMessageContent.vue')
const { applyAgentRuntimeEvents, runtimeTraceFromExtraData } = await server.ssrLoadModule('/src/types/agentRuntime.ts')
const render = run => renderToString(h(Overview, { runtimeTrace: run }))
const worker = (id, overrides = {}) => member({ worker_session_id: id, worker_agent_id: id, worker_agent_name: `${id}助手`, ...overrides })

test('按真实团队分组，仅两个及以上不同成员呈现紧凑概览', async () => {
  const run = trace([], { collaborations: [worker('资料'), worker('风险', { work_status: 'running' }),
    worker('单人', { team_id: 'single', team_name: '单人团队' }), worker('无团队', { team_id: '' })] })
  const teams = present(run)
  assert.equal(teams.length, 1)
  assert.equal(teams[0].completedCount, 1)
  assert.equal(teams[0].members.length, 2)
  const html = await render(run)
  assert.match(html, /资料协同 · 已完成 1\/2/)
  assert.match(html, /<details[^>]*class="agent-team-overview"/)
  assert.match(html, /<summary/)
  assert.doesNotMatch(html, /单人团队|无团队助手/)
})

test('多团队独立计数，相同会话标识不会跨团队合并', () => {
  const run = trace([], { collaborations: [worker('one'), worker('two'),
    worker('one', { team_id: 'other', team_name: '核验团队', work_status: 'failed' }),
    worker('three', { team_id: 'other', team_name: '核验团队', work_status: 'queued' })] })
  assert.deepEqual(present(run).map(team => [team.id, team.completedCount, team.members.length]), [['team', 2, 2], ['other', 0, 2]])
})

test('同成员采用最高工作版本；迟到旧版本成功不能覆盖新版本未完成', () => {
  const run = trace([], { collaborations: [worker('资料', { work_revision: 2, work_status: 'running', updated_at: at(3) }),
    worker('资料', { work_revision: 1, work_status: 'completed', updated_at: at(5) }), worker('风险')] })
  const teams = present(run)
  assert.equal(teams[0].members.length, 2)
  assert.equal(teams[0].members[0].revision, 2)
  assert.equal(teams[0].members[0].state, 'running')
  assert.equal(teams[0].completedCount, 1)
})

test('同版本采用最新更新时间，不因旧快照或重复事件增加成员', () => {
  const run = trace([], { collaborations: [worker('资料', { work_status: 'completed', updated_at: at(5) }),
    worker('资料', { work_status: 'running', updated_at: at(2) }), worker('风险')] })
  assert.equal(present(run)[0].completedCount, 2)
  assert.equal(present(run)[0].members.length, 2)
})

test('仅 reported/completed 计为完成；未知、失败和派发成功不误算', () => {
  for (const state of ['unknown', 'success', 'failed', 'error', 'finished', 'queued', 'idle', 'running', 'interrupted']) {
    const run = trace([message('dispatch', [toolCall('call', 'agent_invoke'), toolResult('call', 'agent_invoke')])],
      { collaborations: [worker('资料', { work_status: state }), worker('风险', { work_status: 'completed' })] })
    assert.equal(present(run)[0].completedCount, 1, state)
  }
  const dispatchOnly = trace([message('dispatch', [toolCall('a', 'AgentInvite'), toolResult('a', 'AgentInvite'),
    toolCall('b', 'AgentInvite'), toolResult('b', 'AgentInvite')])])
  assert.deepEqual(present(dispatchOnly), [])
})

test('仅当前版本登记工作标题可见，不复制历史工具记录、原始参数或确认', async () => {
  const current = { ...activity('dobby_list_project_tasks'), label: '原始内部阶段',
    presentation: { label: '核对工期安排', source: 'registration', category: 'database' } }
  const run = trace([], { collaborations: [worker('资料', { current_activity: current,
    activities: [activity('Read'), activity('weknora_search')] }), worker('风险', {
    current_activity: { ...current, presentation: null, tool_name: 'secret_tool_name' } })],
    subagentHitl: [{ event_type: 'require_user_confirm', event: { tool_calls: [toolCall('private', 'secret_tool', { secret: '绝密参数' })] } }] })
  const before = structuredClone(run)
  const html = await render(run)
  assert.match(html, /核对工期安排/)
  assert.doesNotMatch(html, /原始内部阶段|secret_tool|绝密参数|读取文件|检索知识库|确认执行/)
  assert.deepEqual(run, before)
})

test('历史、停止中与已停止的成员不转圈，不把未完成成员算为完成', async () => {
  const run = trace([], { collaborations: [worker('资料', { work_status: 'running' }), worker('风险')] })
  for (const status of ['completed', 'interrupting', 'interrupted', 'awaiting_permission']) {
    run.status = status
    const overview = present(run)[0]
    assert.equal(overview.members[0].state, 'running')
    assert.equal(overview.members[0].running, false)
    assert.equal(overview.completedCount, 1)
    assert.doesNotMatch(await render(run), /class="spin"/)
  }
  run.status = 'running'
  assert.match(await render(run), /class="spin"/)
})

test('流式状态与历史还原生成同一团队概览，原消息时序不改变', () => {
  const run = trace([message('first', [toolCall('a', 'AgentInvite')]), message('later', [toolCall('b', 'AgentInvite')])],
    { status: 'running', collaborations: [worker('资料', { work_status: 'running' }), worker('风险')] })
  const before = structuredClone(run)
  const updated = applyAgentRuntimeEvents(run, [{ type: 'CUSTOM', name: 'collaboration_member_updated',
    value: worker('资料', { work_status: 'completed', updated_at: at(5) }) }])
  assert.equal(present(updated)[0].completedCount, 2)
  assert.deepEqual(present(runtimeTraceFromExtraData(persistedExtra(updated))), present(updated))
  assert.deepEqual(run, before)
  assert.deepEqual(updated.messages.map(message => message.id), ['first', 'later'])
})

test('完整用户消息必须接入团队概览，历史加载仍显示成员总数与完成计数', async () => {
  const run = trace([message('answer', [{ type: 'text', id: 'answer-text', text: '工程资料已核对。' }])], {
    collaborations: [worker('资料', { work_status: 'completed' }), worker('风险', { work_status: 'failed' })],
  })
  const restored = runtimeTraceFromExtraData(persistedExtra(run))
  const html = await renderToString(h(MessageContent, { runtimeTrace: restored }))
  assert.match(html, /class="agent-team-overview"/)
  assert.match(html, /资料协同 · 已完成 1\/2/)
  assert.match(html, /aria-label="团队成员当前进度"/)
  assert.match(html, /data-worker-id="资料"/)
  assert.match(html, /data-worker-id="风险"/)
  assert.match(html, /工程资料已核对。/)
})
