import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'
import { defineComponent, h } from 'vue'
import { renderToString } from '@vue/server-renderer'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom', logLevel: 'error' })
after(() => server.close())
const { default: Table } = await server.ssrLoadModule('/src/components/initialization/InitializationSectionTable.vue')
const { buildInitializationChangeTree } = await server.ssrLoadModule('/src/utils/initializationChangeTree.ts')
const { groupInitializationTableRows, initializationSectionTableRows, initializationResolutionValue, parseInitializationResolution } = await server.ssrLoadModule('/src/utils/initializationSectionTable.ts')
const change = (section, key, after, extra = {}) => ({ key, section, record_id: 1, title: `${section}-${key}`, operation: 'add', target_id: null,
  before: null, after, fields: [], selected: true, candidates: [], ...extra })
const rows = changes => buildInitializationChangeTree(changes, changes).rows
const render = (section, changes, extra = {}) => renderToString(h(Table, { section, rows: rows(changes), selectedKeys: changes.map(item => item.key), resolutions: {}, issues: [], admin: true, applying: false, collapsedKeys: new Set(), ...extra }))

test('工程字段逐项直接比较，单条只呈现自己的字段，新增不重复旧值列', async () => {
  const after = { name: '新项目', construction_unit_name: '新建设单位' }, before = { name: '原项目', construction_unit_name: '原建设单位' }
  const changes = Object.keys(after).map(field => change('project', `project:1:${field}`, after, {
    operation: 'update', before, fields: [{ name: field, before: before[field], after: after[field] }],
  }))
  const html = await render('project', changes)
  assert.match(html, /<th[^>]*>现有数据<\/th>/)
  for (const text of ['原项目', '新项目', '原建设单位', '新建设单位']) assert.equal(html.split(text).length - 1, 1, text)
  assert.doesNotMatch(html, /<details|逐项确认|点击查看/)
  for (const operation of ['add', 'unchanged']) {
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
  assert.doesNotMatch(html, /暂无已有账号|<th[^>]*>已有账号<\/th>/)
  const personRow = html.match(/<tbody[^>]*data-person-key="p1"[\s\S]*?<\/tbody>/)?.[0]
  assert.match(personRow, /person-account-row[\s\S]*zhang.gong/)
})

test('同一人岗位归组后只显示一套明文凭据，岗位仍独立保留，其他人员互不串用', async () => {
  const changes = [change('personnel', 'p1', { real_name: '张工', position_name: '施工员', identity_card_no: 'one' }),
    change('personnel', 'p2', { real_name: '李工', position_name: '质量员', identity_card_no: 'two' }),
    change('personnel', 'p3', { real_name: '张工', position_name: '安全员', identity_card_no: 'one' })]
  const credentials = [{ identity_card_no: 'one', real_name: '张工', position_name: '施工员', username: 'zhang.gong', initial_password: 'Abc12345!xyz' },
    { identity_card_no: 'two', real_name: '李工', position_name: '质量员', username: 'li.gong', initial_password: 'Def12345!xyz' }]
  for (const username of ['zhang.gong', 'changed.zhang']) {
    credentials[0].username = username
    const html = await render('personnel', changes, { credentials })
    const bodies = [...html.matchAll(/<tbody\b[^>]*>[\s\S]*?<\/tbody>/g)].map(match => match[0])
    assert.equal(bodies.length, 2)
    assert.match(bodies[0], /施工员[\s\S]*安全员[\s\S]*person-account-row[\s\S]*登录账号[\s\S]*初始密码/)
    assert.match(bodies[0], /data-change-key="p1"/)
    assert.match(bodies[0], /data-change-key="p3"/)
    assert.equal(bodies[0].split(`value="${username}"`).length - 1, 1)
    assert.equal(bodies[0].split('value="Abc12345!xyz"').length - 1, 1)
    assert.doesNotMatch(bodies[0], /li.gong|Def12345/)
    assert.match(bodies[0].match(/<input[^>]*aria-label="张工的初始密码"[^>]*>/)[0], /type="text"/)
    assert.match(bodies[1], /li.gong[\s\S]*Def12345/)
    assert.doesNotMatch(html, /暂无已有账号|本次新增人员账号/)
  }
  const restricted = await render('personnel', changes, { credentials, admin: false })
  assert.doesNotMatch(restricted, /Abc12345|Def12345|type="password"/)
  const pending = await render('personnel', [changes[0]], { credentials, applying: true })
  for (const input of pending.match(/<input\b[^>]*>/g)) assert.match(input, /disabled/)
  const errorHtml = await render('personnel', changes, { credentials, credentialErrors: { one: '账号重复，请调整。' } })
  const errorRows = [...errorHtml.matchAll(/<tbody\b[^>]*>[\s\S]*?<\/tbody>/g)].map(match => match[0])
  assert.match(errorRows[0], /账号重复，请调整。/)
  assert.doesNotMatch(errorRows[1], /账号重复，请调整。/)
  const oneRoleSelected = await render('personnel', changes, { credentials, selectedKeys: ['p1'] })
  assert.doesNotMatch(oneRoleSelected.match(/<input[^>]*aria-label="张工的登录账号"[^>]*>/)[0], /disabled/)
  const filtered = await render('personnel', [changes[2]], { credentials })
  assert.match(filtered, /安全员[\s\S]*changed.zhang/)
  assert.doesNotMatch(filtered, /施工员/)
})

test('兼任提醒在姓名下方、全部岗位上方每人仅显示一次，筛选任一岗位仍可见', async () => {
  const changes = [change('personnel', 'p1', { real_name: '张工', position_name: '施工员', identity_card_no: 'one' }),
    change('personnel', 'p2', { real_name: '李工', position_name: '施工员', identity_card_no: 'two' }),
    change('personnel', 'p3', { real_name: '张工', position_name: '安全员', identity_card_no: 'one' })]
  const issues = changes.flatMap(item => [
    { level: 'warning', section: 'personnel', change_key: item.key, field_name: 'position_name', rule_id: 'personnel.multiple_positions', title: '兼任核对', message: '请核对本人兼任，岗位共用账号。' },
    { level: 'warning', section: 'personnel', change_key: item.key, field_name: 'certificate_no', rule_id: 'personnel.certificate_review', title: '证书核对', message: '请核对此岗位的证书。' },
    { level: 'error', section: 'personnel', change_key: item.key, field_name: 'responsibility_description', rule_id: 'required_field', title: '职责缺失', message: '请补充此岗位的职责。' },
  ])
  const original = structuredClone(issues)
  const html = await render('personnel', changes, { issues })
  const bodies = [...html.matchAll(/<tbody\b[^>]*>[\s\S]*?<\/tbody>/g)].map(match => match[0])
  assert.equal(bodies.length, 2)
  for (const body of bodies) {
    assert.equal(body.split('请核对本人兼任，岗位共用账号。').length - 1, 1)
    const renderedRows = [...body.matchAll(/<tr\b[^>]*>[\s\S]*?<\/tr>/g)].map(match => match[0])
    assert.match(renderedRows[0], /class="person-header"/)
    assert.match(renderedRows[1], /class="person-issues-row"[\s\S]*请核对本人兼任，岗位共用账号。/)
    const roleRows = renderedRows.filter(row => /class="[^"]*\brecord-row\b/.test(row))
    assert.ok(roleRows.length)
    for (const roleRow of roleRows) assert.doesNotMatch(roleRow, /请核对本人兼任，岗位共用账号。/)
  }
  for (const message of ['请核对此岗位的证书。', '请补充此岗位的职责。']) {
    assert.equal(bodies[0].split(message).length - 1, 2)
    assert.equal(bodies[1].split(message).length - 1, 1)
  }
  for (const item of [changes[0], changes[2]]) {
    const filtered = await render('personnel', [item], { issues })
    assert.equal(filtered.split('请核对本人兼任，岗位共用账号。').length - 1, 1)
    assert.match(filtered, /class="person-issues-row"[\s\S]*请核对本人兼任，岗位共用账号。[\s\S]*class="[^"]*\brecord-row\b/)
  }
  assert.deepEqual(issues, original)
})

test('人员按身份证归组而不按姓名，缺身份证不合并，分组不改变源岗位记录', () => {
  const changes = [change('personnel', 'a', { real_name: '同名人员', identity_card_no: 'id-a' }),
    change('personnel', 'b', { real_name: '同名人员', identity_card_no: 'id-b' }),
    change('personnel', 'c', { real_name: '同名人员', identity_card_no: 'id-a' }),
    change('personnel', 'd', { real_name: '无证件' }), change('personnel', 'e', { real_name: '无证件' })]
  const original = structuredClone(changes)
  const groups = groupInitializationTableRows(rows(changes), 'personnel')
  assert.deepEqual(groups.map(group => group.rows.map(row => row.change.key)), [['a', 'c'], ['b'], ['d'], ['e']])
  assert.deepEqual(changes, original)
})

test('WBS保持完整层级与主列；折叠只隐藏后代，筛选祖先不可勾选', async () => {
  const changes = [change('wbs', 'root', { wbs_code: '1', name: '主体工程', duration_hours: 0, progress_percent: 0, status_text: 'in_progress', assigned_to_text: '王工', planned_start_at: '2026-09-10T08:00:00.123+08:00', planned_finish_at: '2026-09-11T18:00:00+08:00', priority_text: 'high' }),
    change('wbs', 'child', { wbs_code: '1.1', parent_wbs_code: '1', name: '混凝土浇筑' }),
    change('wbs', 'other', { wbs_code: '2', name: '外立面工程' })]
  const html = await render('wbs', changes)
  for (const text of ['主体工程', '混凝土浇筑', '外立面工程', '进行中', '高优先级', '王工', '2026-09-10 08:00:00.123+08:00', '2026-09-11 18:00:00+08:00']) assert.ok(html.includes(text), text)
  assert.match(html, /工期（小时）[\s\S]*>0<\/strong>/)
  assert.match(html, />0%<\/strong>/)
  assert.match(html, /aria-expanded="true"/)
  const collapsed = await render('wbs', changes, { collapsedKeys: new Set(['root']) })
  assert.doesNotMatch(collapsed, /混凝土浇筑/)
  assert.match(collapsed, /主体工程|外立面工程/)
  const filtered = buildInitializationChangeTree(changes, [changes[1]]).rows
  const contextHtml = await render('wbs', changes, { rows: filtered })
  assert.match(contextHtml, /上级路径/)
  const checkboxes = [...contextHtml.matchAll(/<input[^>]*aria-label="选择[^>]*>/g)].map(match => match[0])
  assert.match(checkboxes[0], /disabled/)
  assert.doesNotMatch(checkboxes[0], /checked/)
  assert.doesNotMatch(checkboxes[1], /disabled/)
})

test('WBS主列保留前置工序和状态，更多字段默认收起但其中的修改与核验问题直接可见', async () => {
  const item = change('wbs', 'node', { wbs_code: '1.1', parent_wbs_code: '1', name: '混凝土施工', predecessor_wbs_codes: ['1.0'], status_text: 'in_progress', priority_text: 'high', source_creator: '来源作者甲', budget: 0 })
  const html = await render('wbs', [item])
  for (const text of ['计划层级 / 工序名称', '计划区间', '工期与负责人', '完成进度', '状态与优先级', '前置 / 上级工序', '1.0', '进行中', '高优先级']) assert.ok(html.includes(text), text)
  assert.doesNotMatch(html, /来源作者甲|data-field="budget"/)
  const annotated = await render('wbs', [item], { issues: [{ section: 'wbs', change_key: 'node', field_name: 'budget', level: 'warning', title: 'MCP提示', message: '原始预算待核对' }] })
  assert.match(annotated, /data-field="budget"[\s\S]*原始预算待核对/)
  const changed = await render('wbs', [{ ...item, operation: 'update', before: { source_creator: '来源作者乙' }, fields: [{ name: 'source_creator', before: '来源作者乙', after: '来源作者甲' }] }])
  assert.match(changed, /来源作者乙[\s\S]*来源作者甲/)
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

test('字段错误就地展示，不提供人工选择新建或覆盖的入口', async () => {
  const conflicted = change('personnel', 'person', { real_name: '同名人员' }, { operation: 'conflict', candidates: [{ id: 7, title: '原岗位人员' }] })
  const html = await render('personnel', [conflicted], { resolutions: { person: null }, issues: [{ level: 'error', section: 'personnel', change_key: 'person', field_name: 'identity_card_no', title: '证件缺失', message: '补充身份证号', suggestion: '核对人员名单' }] })
  for (const text of ['证件缺失', '身份证号', '补充身份证号', '核对人员名单']) assert.ok(html.includes(text), text)
  assert.doesNotMatch(html, /<select|匹配已有记录|作为新增记录/)
  assert.equal(initializationResolutionValue(conflicted, { person: null }), 'new')
  assert.equal(parseInitializationResolution('new'), null)
  assert.equal(parseInitializationResolution('7'), 7)
  assert.equal(parseInitializationResolution(''), undefined)
  assert.equal(parseInitializationResolution('bad'), undefined)
})

test('同条质量记录的四处缺失各自进入对应字段，补充字段的问题也就地显示', async () => {
  const fields = ['quality_acceptance_item', 'control_indicator', 'inspection_frequency', 'related_documents', 'summary']
  const item = change('quality_requirements', 'missing', { wbs_code: '1.1.3' })
  const issues = fields.map(field => ({ section: item.section, change_key: item.key, field_name: field, level: 'error', title: field, message: `修正-${field}` }))
  const html = await render(item.section, [item], { issues })
  const cells = [...html.matchAll(/<td\b[^>]*>[\s\S]*?<\/td>/g)].map(match => match[0])
  for (const field of fields) {
    const cell = cells.find(cell => cell.includes(`data-field="${field}"`))
    assert.ok(cell, field)
    assert.ok(cell.includes(`修正-${field}`), field)
    assert.equal(cells.filter(cell => cell.includes(`修正-${field}`)).length, 1)
    for (const other of fields.filter(name => name !== field)) assert.ok(!cell.includes(`修正-${other}`), `${field} / ${other}`)
  }
})

test('WBS树列跨过补充信息行，记录级问题保留在名称列', async () => {
  const item = change('wbs', 'root', { wbs_code: '1', name: '基础工程', description: '基础施工说明' })
  const html = await render('wbs', [item], { issues: [{ section: 'wbs', change_key: 'root', level: 'warning', title: '核对匹配', message: '记录存在重复' }] })
  const cells = [...html.matchAll(/<td\b[^>]*>[\s\S]*?<\/td>/g)].map(match => match[0])
  const identity = cells.find(cell => cell.includes('hierarchy-cell'))
  assert.match(identity, /rowspan="2"/)
  assert.match(identity, /记录存在重复/)
  assert.match(html, /colspan="6"/)
})

test('只读或提交中禁用选择和匹配，已提交无变化不可再次勾选，空态不隐藏其他分区', async () => {
  const pending = change('personnel', 'p', { real_name: '张工' }, { operation: 'conflict', candidates: [{ id: 1, title: '张工旧岗位' }] })
  for (const options of [{ admin: false }, { applying: true }]) {
    const html = await render('personnel', [pending], options)
    for (const control of html.match(/<(?:input|select)[^>]*>/g)) assert.match(control, /disabled/)
  }
  for (const operation of ['unchanged']) {
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

test('已提交记录退出草稿表格，旧匹配决定也不会恢复人工选择入口', async () => {
  const matched = change('personnel', 'matched', { real_name: '张工' }, { operation: 'unchanged', target_id: 7, candidates: [{ id: 7, title: '原施工员' }] })
  assert.doesNotMatch(await render('personnel', [matched], { resolutions: { matched: 7 } }), /<select|作为新增记录/)
  const applied = { ...matched, operation: 'applied' }
  assert.equal(initializationSectionTableRows(rows([applied]), 'personnel', new Set(), []).length, 0)
  assert.doesNotMatch(await render('personnel', [applied]), /张工|已提交|record-row/)
})
