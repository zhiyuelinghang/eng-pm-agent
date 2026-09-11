import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'
import { h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { trace, message, textBlock, toolCall, toolResult, member } from './fixtures/agentConversation.mjs'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom', logLevel: 'error' })
after(() => server.close())
const { default: Content } = await server.ssrLoadModule('/src/components/agent/AgentMessageContent.vue')
const { default: Table } = await server.ssrLoadModule('/src/components/initialization/InitializationSectionTable.vue')
const { buildInitializationChangeTree } = await server.ssrLoadModule('/src/utils/initializationChangeTree.ts')
const { initializationReviewIssues } = await server.ssrLoadModule('/src/utils/initializationReviewIssues.ts')
const { agentRuntimeSummary } = await server.ssrLoadModule('/src/utils/agentRuntimeSummary.ts')
const { showInitializationDraftDock } = await server.ssrLoadModule('/src/utils/initializationDraftDock.ts')

test('资料卡片等待本轮专家和核验结束；有业务错误仍需显示供人工修正', () => {
  for (const status of ['collecting', 'reviewing', 'building', 'rejected', 'applied']) assert.equal(showInitializationDraftDock({ status }, false), false)
  for (const status of ['ready', 'invalid', 'partially_applied']) {
    assert.equal(showInitializationDraftDock({ status }, true), false)
    assert.equal(showInitializationDraftDock({ status }, false), true)
  }
  assert.equal(showInitializationDraftDock({ status: 'ready', pending_change_count: 0 }, false), false)
  assert.equal(showInitializationDraftDock({ status: 'collecting', validation: { status: 'failed' } }, false), true)
})

test('运行和历史回复保留模型、用量、输出长度、等待成员；初始化隐藏计划调用但保留其他工作', async () => {
  const run = trace([message('reply', [toolCall('plan', 'TaskCreate', { subject: '建立计划' }), toolResult('plan', 'TaskCreate', '{}'), textBlock('资料正在核验')])], {
    status: 'running', turnFinishedAt: null, modelNames: ['实际模型'],
    collaborations: [member({ work_status: 'running', worker_agent_name: 'WBS与进度专家', settled_at: null })],
  })
  run.messages[0].usage = { input_tokens: 1024, output_tokens: 80 }
  const summary = agentRuntimeSummary(run)
  assert.deepEqual(summary.usage, { input: 1024, output: 80 })
  assert.equal(summary.outputLength, 6)
  const live = await renderToString(h(Content, { runtimeTrace: run, showTaskPlan: false }))
  for (const label of ['总耗时', '实际模型', '1,024', '80', '输出 6 字符', '等待：WBS与进度专家']) assert.ok(live.includes(label), label)
  assert.doesNotMatch(live, /创建执行计划|执行计划完成进度/)
  const saved = await renderToString(h(Content, { runtimeTrace: { ...run, status: 'completed', turnFinishedAt: run.messages[0].created_at }, showTaskPlan: false }))
  assert.match(saved, /实际模型|输出 6 字符/)
  assert.doesNotMatch(saved, /等待：/)
})

test('新MCP结果取代所选记录的旧判定，未选择的记录仍保留上次核验结果', () => {
  const changes = ['a', 'b'].map((key, index) => ({ key, record_id: index + 1, section: 'quality_requirements', title: key, operation: 'add', after: { wbs_code: key }, fields: [] }))
  const issues = changes.map(change => ({ rule_id: 'old.rule', section: change.section, change_key: change.key, level: 'error', field_name: 'control_indicator', title: '旧错误', message: '旧规则要求' }))
  const draft = { id: 1, revision: 1, status: 'invalid', validation_issues: issues }
  assert.deepEqual(initializationReviewIssues(draft, changes, [], ['a'], true).map(issue => issue.change_key), ['b'])
  assert.equal(initializationReviewIssues(draft, changes, [], ['a'], false).length, 2)
})

test('未选中记录的错误仍保留在缺失字段所在单元格，只提示人工修正原始资料后重新上传', async () => {
  const change = { key: '3', record_id: 3, section: 'quality_requirements', title: '', operation: 'add', target_id: null, before: null, after: { wbs_code: '1.2' }, fields: [], selected: false, candidates: [] }
  const issue = { rule_id: 'quality.missing', target_record_id: 3, section: 'quality_requirements', level: 'error', field_name: 'control_indicator', title: '缺少控制指标', message: '原表未填写控制指标', suggestion: '请补充原始资料' }
  const issues = initializationReviewIssues({ id: 1, revision: 1, status: 'invalid', validation_issues: [issue] }, [change], [{ ...issue, change_key: '3' }], [])
  assert.equal(issues.length, 1)
  assert.equal(issues[0].selected, false)
  const html = await renderToString(h(Table, { section: change.section, rows: buildInitializationChangeTree([change], [change]).rows, selectedKeys: [], resolutions: {}, issues, collapsedKeys: new Set(), applying: false, admin: true }))
  for (const label of ['1.2', '未填写', '原表未填写控制指标', '请补充原始资料', '请修改原始资料后重新上传，核验通过后才能入库。']) assert.ok(html.includes(label), label)
  const cells = [...html.matchAll(/<td\b[^>]*>[\s\S]*?<\/td>/g)].map(item => item[0])
  assert.match(cells.find(cell => cell.includes('data-field="control_indicator"')), /原表未填写控制指标/)
  assert.equal(cells.filter(cell => cell.includes('原表未填写控制指标')).length, 1)
  assert.doesNotMatch(html, /完整核验问题列表|定位资料|record-issues|在对话中修正|<button/)
  assert.doesNotMatch(html.match(/<input[^>]*>/)[0], /checked/)
})

test('WBS 问题字段和说明原样来自 MCP，前端不解释规则编号或推导业务结论', () => {
  const changes = [{ key: '0', record_id: 1, section: 'wbs', title: '1.1', operation: 'add', after: { wbs_code: '1.1' }, fields: [] }]
  for (const rule_id of ['wbs.predecessor_overlap', 'wbs.sibling_start_order', 'custom.rule']) {
    const original = { rule_id, change_key: '0', section: 'wbs', level: 'warning', field_name: 'planned_finish_at', title: 'MCP 标注', message: 'MCP 指定的原始说明', details: { wbs_code: '1.2' } }
    const [displayed] = initializationReviewIssues(null, changes, [original], ['0'])
    for (const field of ['rule_id', 'level', 'field_name', 'title', 'message', 'details']) assert.deepEqual(displayed[field], original[field])
  }
})
