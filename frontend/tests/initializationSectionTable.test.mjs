import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'
import { defineComponent, h } from 'vue'
import { renderToString } from '@vue/server-renderer'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom', logLevel: 'error' })
after(() => server.close())
const { default: Table } = await server.ssrLoadModule('/src/components/initialization/InitializationSectionTable.vue')
const { buildInitializationChangeTree } = await server.ssrLoadModule('/src/utils/initializationChangeTree.ts')
const { initializationSectionTableRows, initializationResolutionValue, parseInitializationResolution } = await server.ssrLoadModule('/src/utils/initializationSectionTable.ts')
const change = (section, key, after, extra = {}) => ({ key, section, record_id: 1, title: `${section}-${key}`, operation: 'add', target_id: null,
  before: null, after, fields: [], selected: true, candidates: [], ...extra })
const rows = changes => buildInitializationChangeTree(changes, changes).rows
const render = (section, changes, extra = {}) => renderToString(h(Table, { section, rows: rows(changes), selectedKeys: changes.map(item => item.key), resolutions: {}, issues: [], admin: true, applying: false, collapsedKeys: new Set(), ...extra }))

test('工程字段逐项直接比较，单条只呈现自己的字段，新增和已提交不重复旧值列', async () => {
  const after = { name: '新项目', construction_unit_name: '新建设单位' }, before = { name: '原项目', construction_unit_name: '原建设单位' }
  const changes = Object.keys(after).map(field => change('project', `project:1:${field}`, after, {
    operation: 'update', before, fields: [{ name: field, before: before[field], after: after[field] }],
  }))
  const html = await render('project', changes)
  assert.match(html, /<th[^>]*>现有数据<\/th>/)
  for (const text of ['原项目', '新项目', '原建设单位', '新建设单位']) assert.equal(html.split(text).length - 1, 1, text)
  assert.doesNotMatch(html, /<details|逐项确认|点击查看/)
  for (const operation of ['add', 'applied', 'unchanged']) {
    const simple = await render('project', changes.map(item => ({ ...item, operation })))
    assert.doesNotMatch(simple, /现有数据|原项目|原建设单位/)
    assert.match(simple, /本次资料/)
  }
})

test('多条人员的姓名岗位、账号、证件、职责及补充差异全部直接可见', async () => {
  const changes = [change('personnel', 'p1', { real_name: '张工', position_name: '施工员', identity_card_no: 'id-one', certificate_no: '新证书', responsibility_description: '负责主体施工', summary: '新的补充信息' }, {
    operation: 'update', before: { certificate_no: '旧证书', summary: '旧的补充信息' }, fields: [{ name: 'certificate_no', before: '旧证书', after: '新证书' }, { name: 'summary', before: '旧的补充信息', after: '新的补充信息' }],
  }), change('personnel', 'p2', { real_name: '李工', position_name: '质量员', identity_card_no: 'id-two', certificate_no: '质量证书', responsibility_description: '负责质量验收' })]
  const html = await render('personnel', changes, { existingAccounts: [{ identity_card_no: 'id-one', username: 'zhang.gong', real_name: '张工' }] })
  for (const text of ['张工', '施工员', '李工', '质量员', 'zhang.gong', '沿用此账号', '旧证书', '新证书', '负责主体施工', '负责质量验收', '旧的补充信息', '新的补充信息']) assert.ok(html.includes(text), text)
  assert.match(html, /aria-label="补充信息"/)
  assert.doesNotMatch(html, /<details|type="password"/)
})

test('WBS保持完整层级与主列；折叠只隐藏后代，筛选祖先不可勾选', async () => {
  const changes = [change('wbs', 'root', { wbs_code: '1', name: '主体工程', duration_hours: 0, progress_percent: 0, status_text: 'in_progress', assigned_to_text: '王工', planned_start_at: '2026-09-10T08:00:00.123+08:00', planned_finish_at: '2026-09-11T18:00:00+08:00', priority_text: 'high' }),
    change('wbs', 'child', { wbs_code: '1.1', parent_wbs_code: '1', name: '混凝土浇筑' }),
    change('wbs', 'other', { wbs_code: '2', name: '外立面工程' })]
  const html = await render('wbs', changes)
  for (const text of ['主体工程', '混凝土浇筑', '外立面工程', '进行中', '高优先级', '王工', '2026-09-10 08:00:00.123+08:00', '2026-09-11 18:00:00+08:00']) assert.ok(html.includes(text), text)
  assert.match(html, />0 小时<\/strong>/)
  assert.match(html, />0%<\/strong>/)
  assert.match(html, /aria-expanded="true"/)
  const collapsed = await render('wbs', changes, { collapsedKeys: new Set(['root']) })
  assert.doesNotMatch(collapsed, /混凝土浇筑/)
  assert.match(collapsed, /主体工程|外立面工程/)
  const filtered = buildInitializationChangeTree(changes, [changes[1]]).rows
  const contextHtml = await render('wbs', changes, { rows: filtered })
  assert.match(contextHtml, /上级路径/)
  const checkboxes = [...contextHtml.matchAll(/<input[^>]*>/g)].map(match => match[0])
  assert.match(checkboxes[0], /disabled/)
  assert.doesNotMatch(checkboxes[0], /checked/)
  assert.doesNotMatch(checkboxes[1], /disabled/)
})

test('风险与质量主列按业务展示，所有非主列变化仍在本行直接展示', async () => {
  const risk = change('risks', 'r', { risk_part: '基坑', related_process_name: '土方开挖', risk_level: '高风险', risk_window_start_date: '2026-09-10', risk_window_end_date: '2026-09-20', evaluation_condition: '深度超过5米', summary: '加强排水' })
  for (const text of ['基坑', '土方开挖', '高风险', '2026-09-10', '2026-09-20', '深度超过5米', '加强排水']) assert.ok((await render('risks', [risk])).includes(text), text)
  const quality = change('quality_requirements', 'q', { wbs_code: '1.1', quality_acceptance_item: '混凝土强度', control_indicator: 'C40', inspection_frequency: '每100立方米一组', related_documents: ['施工方案', '试验报告'], summary: '核对留样条件' }, {
    operation: 'update', before: { control_indicator: 'C30' }, fields: [{ name: 'control_indicator', before: 'C30', after: 'C40' }],
  })
  const html = await render('quality_requirements', [quality])
  for (const text of ['混凝土强度', 'C30', 'C40', '每100立方米一组', '施工方案、试验报告', '核对留样条件']) assert.ok(html.includes(text), text)
  assert.doesNotMatch(html, /<details/)
})

test('冲突选择和字段错误在对应行展开显示，新增解析保持null语义', async () => {
  const conflicted = change('personnel', 'person', { real_name: '同名人员' }, { operation: 'conflict', candidates: [{ id: 7, title: '原岗位人员' }] })
  const html = await render('personnel', [conflicted], { resolutions: { person: null }, issues: [{ level: 'error', section: 'personnel', change_key: 'person', field_name: 'identity_card_no', title: '证件缺失', message: '补充身份证号', suggestion: '核对人员名单' }] })
  for (const text of ['匹配已有记录', '原岗位人员', '作为新增记录', '证件缺失', '身份证号', '补充身份证号', '核对人员名单']) assert.ok(html.includes(text), text)
  assert.equal(initializationResolutionValue(conflicted, { person: null }), 'new')
  assert.equal(parseInitializationResolution('new'), null)
  assert.equal(parseInitializationResolution('7'), 7)
  assert.equal(parseInitializationResolution(''), undefined)
  assert.equal(parseInitializationResolution('bad'), undefined)
})

test('只读或提交中禁用选择和匹配，已提交无变化不可再次勾选，空态不隐藏其他分区', async () => {
  const pending = change('personnel', 'p', { real_name: '张工' }, { operation: 'conflict', candidates: [{ id: 1, title: '张工旧岗位' }] })
  for (const options of [{ admin: false }, { applying: true }]) {
    const html = await render('personnel', [pending], options)
    for (const control of html.match(/<(?:input|select)[^>]*>/g)) assert.match(control, /disabled/)
  }
  for (const operation of ['applied', 'unchanged']) {
    const html = await render('personnel', [{ ...pending, operation }])
    assert.match(html.match(/<input[^>]*>/)[0], /disabled/)
    assert.doesNotMatch(html.match(/<input[^>]*>/)[0], /checked/)
    assert.doesNotMatch(html, /<select/)
  }
  const snapshot = [pending, change('risks', 'r', { risk_part: '基坑' })], before = structuredClone(snapshot)
  assert.equal(initializationSectionTableRows(rows(snapshot), 'personnel', new Set(), []).length, 1)
  assert.match(await render('wbs', snapshot), /暂无符合当前筛选/)
  assert.deepEqual(snapshot, before)
})

test('显式匹配后成为无变化仍可改选或新增，无匹配和已提交不提供重选入口', async () => {
  const matched = change('personnel', 'matched', { real_name: '张工' }, { operation: 'unchanged', target_id: 7, candidates: [{ id: 7, title: '原施工员' }, { id: 8, title: '另一岗位' }] })
  const html = await render('personnel', [matched], { resolutions: { matched: 7 } })
  assert.match(html, /<select/)
  assert.doesNotMatch(html.match(/<select[^>]*>/)[0], /disabled/)
  assert.match(html.match(/<input[^>]*>/)[0], /disabled/)
  assert.match(html, /另一岗位|作为新增记录/)
  assert.doesNotMatch(await render('personnel', [matched]), /<select/)
  assert.doesNotMatch(await render('personnel', [{ ...matched, operation: 'applied' }], { resolutions: { matched: 7 } }), /<select/)
})

test('无变化匹配行能发出改选事件，权限或处理中仍阻止实际匹配动作', async () => {
  // Invoke the component's actual setup handlers in an SSR context, without a browser or API.
  const matched = change('personnel', 'matched', { real_name: '张工' }, { operation: 'unchanged', target_id: 7, candidates: [{ id: 7, title: '原岗位' }] })
  for (const restriction of [{}, { admin: false }, { applying: true }, { contextOnly: true }]) {
    const events = [], treeRows = rows([matched]); treeRows[0].contextOnly = Boolean(restriction.contextOnly)
    const Harness = defineComponent({ setup() {
      const setup = Table.setup({ section: 'personnel', rows: treeRows, selectedKeys: [], resolutions: { matched: 7 }, issues: [], admin: true, applying: false, collapsedKeys: new Set(), ...restriction }, {
        emit: (event, item, target) => { if (event === 'resolve') events.push([item.key, target]) },
        expose: () => {},
      })
      for (const value of ['new', '7', '']) setup.resolveRow(treeRows[0], { target: { value } })
      return () => null
    } })
    await renderToString(h(Harness))
    assert.deepEqual(events, Object.keys(restriction).length ? [] : [['matched', null], ['matched', 7], ['matched', undefined]])
  }
})
