import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom', logLevel: 'error' })
after(() => server.close())
const { buildInitializationChangeTree, visibleInitializationChangeTreeRows } = await server.ssrLoadModule('/src/utils/initializationChangeTree.ts')
const { filterInitializationChanges, formatInitializationChangeValue, initializationComparisonFields, selectableInitializationChange } = await server.ssrLoadModule('/src/utils/initializationChangePresentation.ts')

function wbs(key, code, parent = null, extra = {}) {
  return { key, record_id: Number(key) || 1, section: 'wbs', title: `${code} · 工序`, operation: 'update', target_id: 1, before: { name: '旧工序' }, after: { wbs_code: code, parent_wbs_code: parent, name: '新工序' }, fields: [{ name: 'name', before: '旧工序', after: '新工序' }], selected: true, candidates: [], ...extra }
}

test('WBS按父子关系和自然编码排序，逐级折叠不会改动选中的变更', () => {
  const changes = [wbs('10', '1.10', '1'), wbs('2', '1.2', '1'), wbs('1', '1'), wbs('3', '1.2.1', '1.2')]
  const selected = changes.filter(selectableInitializationChange).map(change => change.key)
  const tree = buildInitializationChangeTree(changes, changes)
  assert.deepEqual(tree.rows.map(row => [row.change.key, row.depth]), [['1', 0], ['2', 1], ['3', 2], ['10', 1]])
  assert.deepEqual(visibleInitializationChangeTreeRows(tree.rows, new Set(['2'])).map(row => row.change.key), ['1', '2', '10'])
  assert.deepEqual(visibleInitializationChangeTreeRows(tree.rows, new Set(tree.groupKeys)).map(row => row.change.key), ['1'])
  assert.equal(visibleInitializationChangeTreeRows(tree.rows, new Set()).length, 4)
  assert.deepEqual(changes.filter(change => change.selected).map(change => change.key), selected)
})

test('搜索子节点保留上级路径，但上级上下文不进入当前筛选批量选择', () => {
  const changes = [wbs('1', '1', null, { operation: 'unchanged', fields: [] }), wbs('2', '1.2', '1'), wbs('3', '1.3', '1')]
  const matching = filterInitializationChanges(changes, 'wbs', 'changes', '1.2')
  const tree = buildInitializationChangeTree(changes, matching)
  assert.deepEqual(tree.rows.map(row => [row.change.key, row.contextOnly]), [['1', true], ['2', false]])
  assert.deepEqual(matching.filter(selectableInitializationChange).map(change => change.key), ['2'])
  assert.deepEqual(initializationComparisonFields(tree.rows[1].change).find(field => field.name === 'name'), {
    name: 'name', label: '名称', before: '旧工序', after: '新工序', changed: true,
  })
})

test('筛选已提交子节点时仍可恢复树路径，其他分区记录不被折叠', () => {
  const project = { ...wbs('4', ''), key: '4:construction_unit_name', section: 'project', operation: 'applied', after: { construction_unit_name: '建设单位' } }
  const changes = [project, wbs('1', '1'), wbs('2', '1.2', '1', { operation: 'applied' })]
  const matching = filterInitializationChanges(changes, 'all', 'applied', '')
  const tree = buildInitializationChangeTree(changes, matching)
  assert.deepEqual(tree.rows.map(row => row.change.key), ['4:construction_unit_name', '1', '2'])
  assert.deepEqual(visibleInitializationChangeTreeRows(tree.rows, new Set(tree.groupKeys)).map(row => row.change.key), ['4:construction_unit_name', '1'])
})

test('重复编码、缺失上级或循环关系的草稿均保持可见，不丢失冲突记录', () => {
  const changes = [wbs('1', '1', null, { operation: 'conflict' }), wbs('2', '1', null, { operation: 'conflict' }), wbs('3', '1.1', '1'), wbs('4', '2', '3'), wbs('5', '3', '2'), wbs('6', '4', 'missing')]
  const tree = buildInitializationChangeTree(changes, changes)
  assert.equal(tree.rows.length, changes.length)
  assert.equal(new Set(tree.rows.map(row => row.change.key)).size, changes.length)
  assert.equal(tree.rows.find(row => row.change.key === '3').depth, 0)
  assert.equal(tree.rows.find(row => row.change.key === '6').depth, 0)
})

test('差异字段恢复中文状态、优先级、节点类型，并可按中文检索', () => {
  assert.equal(formatInitializationChangeValue('in-progress', 'status_text'), '进行中')
  assert.equal(formatInitializationChangeValue('high', 'priority_text'), '高优先级')
  assert.equal(formatInitializationChangeValue('summary_task', 'item_type'), '汇总任务')
  assert.equal(formatInitializationChangeValue('定制节点', 'item_type'), '定制节点')
  const changes = [wbs('1', '1', null, { after: { name: '土方', status_text: 'in_progress' } })]
  assert.equal(filterInitializationChanges(changes, 'wbs', 'all', '进行中').length, 1)
})

test('日期展示简洁，同时新旧时间的小时、精度和时区变化仍能区分', () => {
  assert.equal(formatInitializationChangeValue('2026-09-10', 'contract_start_date'), '2026-09-10')
  assert.equal(formatInitializationChangeValue('2026-09-10T00:00:00', 'planned_start_at'), '2026-09-10')
  assert.equal(formatInitializationChangeValue('2026-09-10T08:30:00.123+08:00', 'planned_start_at'), '2026-09-10 08:30:00.123+08:00')
  assert.notEqual(formatInitializationChangeValue('2026-09-10T08:00:00', 'planned_start_at'), formatInitializationChangeValue('2026-09-10T09:00:00', 'planned_start_at'))
  assert.equal(formatInitializationChangeValue(null, 'planned_start_at'), '未填写')
  assert.equal(formatInitializationChangeValue(0, 'progress_percent'), '0')
})

test('隐藏两边均空的未变字段，保留清空变化、零值和所有有值字段的中文名称', () => {
  const change = wbs('1', '1', null, {
    before: { description: '旧说明', color_value: null, budget: 0, source_creator: null },
    after: { name: '新任务', description: null, color_value: null, budget: 0, source_creator: '李工', predecessor_wbs_codes: [], deadline_at: null },
    fields: [{ name: 'description', before: '旧说明', after: null }],
  })
  const fields = initializationComparisonFields(change)
  assert.equal(fields.some(field => ['color_value', 'predecessor_wbs_codes', 'deadline_at'].includes(field.name)), false)
  assert.equal(fields.find(field => field.name === 'description').changed, true)
  assert.equal(fields.find(field => field.name === 'budget').after, 0)
  assert.equal(fields.find(field => field.name === 'source_creator').label, '来源创建人')
  const optionalWbsFields = ['color_value', 'assigned_to_text', 'deadline_at', 'estimated_hours', 'time_log_minutes', 'description', 'budget', 'actual_cost', 'msp_id', 'msp_uid', 'source_created_at', 'source_creator', 'source_project_path']
  const withValues = wbs('2', '2', null, { after: Object.fromEntries(optionalWbsFields.map(field => [field, '有值'])), fields: [] })
  for (const field of initializationComparisonFields(withValues)) assert.notEqual(field.label, field.name)
})
