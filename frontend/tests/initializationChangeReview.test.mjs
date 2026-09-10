import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { effectScope, reactive } from 'vue'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom', logLevel: 'error' })
after(() => server.close())
const { useInitializationChangeReview } = await server.ssrLoadModule('/src/composables/useInitializationChangeReview.ts')
const presentation = await server.ssrLoadModule('/src/utils/initializationChangePresentation.ts')
const { initializationChangeError } = await server.ssrLoadModule('/src/api/initializationChanges.ts')

function change(key, operation = 'add', section = 'wbs', extra = {}) {
  return { key, record_id: 1, section, title: key, operation, target_id: null, before: null, after: { name: key }, fields: [{ name: 'name', before: null, after: key }], selected: true, candidates: [], ...extra }
}
function preview(changes = [change('wbs:1'), change('wbs:2')], extra = {}) {
  const selected = changes.filter(item => ['add', 'update'].includes(item.operation)).map(item => item.key)
  return { preview_id: 'preview-1', draft_id: 1, draft_revision: 1, baseline_hash: 'baseline-1', changes, selected_keys: selected, issues: [], can_apply: true, required_personnel_credentials: [], validation: { status: 'completed' }, summary: { add: 2, update: 0, unchanged: 0, conflict: 0, applied: 0, selected: selected.length }, ...extra }
}
const tick = () => new Promise(resolve => setTimeout(resolve, 10))
function deferred() { let resolve; let reject; const promise = new Promise((res, rej) => { resolve = res; reject = rej }); return { promise, resolve, reject } }
function review(t, options = {}) {
  const scope = effectScope()
  t.after(() => scope.stop())
  const props = reactive({ open: true, projectId: '7', draft: { id: 1, revision: 1, status: 'collecting' }, admin: true, ...options.props })
  const calls = [], applyCalls = []
  let applied = 0
  const state = scope.run(() => useInitializationChangeReview(props, () => applied++, {
    debounceMs: 0, password: () => 'Abc12345!xyz',
    preview: async (...args) => { calls.push(args); return options.preview ? options.preview(...args) : preview() },
    apply: async (...args) => { applyCalls.push(args); return options.apply ? options.apply(...args) : { result: { status: 'partially_applied', counts: { wbs: 1 } } } },
  }))
  return { props, state, calls, applyCalls, applied: () => applied }
}

test('草稿还在收集或整体无效时，可对已核验的部分生成预览并提交', async t => {
  const { state, props, calls } = review(t)
  await tick()
  assert.equal(calls[0][2].selected_keys, undefined)
  assert.deepEqual(state.selectedKeys.value, ['wbs:1', 'wbs:2'])
  assert.equal(state.canApply.value, true)
  props.draft.status = 'invalid'
  assert.equal(state.canApply.value, true)
})

test('取消一个记录立即使旧预览失效，并只核验余下选择', async t => {
  const { state, calls } = review(t, { preview: async (_pid, _did, input) => preview(undefined, { selected_keys: input.selected_keys ?? ['wbs:1', 'wbs:2'] }) })
  await tick()
  state.selectChange(state.preview.value.changes[0], false)
  assert.equal(state.stale.value, true)
  assert.equal(state.canApply.value, false)
  await tick()
  assert.deepEqual(calls.at(-1)[2].selected_keys, ['wbs:2'])
  assert.deepEqual(state.selectedKeys.value, ['wbs:2'])
  assert.equal(state.canApply.value, true)
})

test('在请求完成前再次选择，迟到的响应不会覆盖最新选择', async t => {
  const old = deferred(), newest = deferred()
  let request = 0
  const { state, calls } = review(t, { preview: async () => { request++; return request === 1 ? preview() : request === 2 ? old.promise : newest.promise } })
  await tick()
  const first = state.preview.value.changes[0], second = state.preview.value.changes[1]
  state.selectChange(first, false)
  await tick()
  state.selectChange(second, false)
  assert.equal(calls[1][3].aborted, true)
  await tick()
  newest.resolve(preview(undefined, { preview_id: 'latest', selected_keys: [], can_apply: false }))
  await tick()
  old.resolve(preview(undefined, { preview_id: 'old', selected_keys: ['wbs:2'] }))
  await tick()
  assert.equal(state.preview.value.preview_id, 'latest')
  assert.deepEqual(state.selectedKeys.value, [])
  assert.equal(state.canApply.value, false)
})

test('待匹配记录可明确新建，null 会按契约发出并纳入本次选择', async t => {
  const conflict = change('risk:3', 'conflict', 'risks', { candidates: [{ id: 9, title: '已有边坡风险' }] })
  const { state, calls } = review(t, { preview: async () => preview([conflict], { selected_keys: [] }) })
  await tick()
  state.resolveChange(conflict, null)
  assert.equal(state.canApply.value, false)
  await tick()
  assert.equal(Object.hasOwn(calls.at(-1)[2].resolutions, 'risk:3'), true)
  assert.equal(calls.at(-1)[2].resolutions['risk:3'], null)
  assert.deepEqual(calls.at(-1)[2].selected_keys, ['risk:3'])
  state.resolveChange(conflict, 9)
  await tick()
  assert.equal(calls.at(-1)[2].resolutions['risk:3'], 9)
})

test('已提交和无变化记录不可勾选，分区全选仅改变指定记录', async t => {
  const changes = [change('p:1', 'add', 'personnel'), change('w:2'), change('w:3', 'applied'), change('w:4', 'unchanged')]
  const { state } = review(t, { preview: async () => preview(changes) })
  await tick()
  state.selectChange(changes[2], true)
  assert.deepEqual(state.selectedKeys.value, ['p:1', 'w:2'])
  state.selectMany(changes.filter(item => item.section === 'wbs'), false)
  assert.deepEqual(state.selectedKeys.value, ['p:1'])
})

test('警告需要明确核对，选择改动后确认状态重置', async t => {
  const { state } = review(t, { preview: async () => preview(undefined, { issues: [{ level: 'warning', section: 'wbs', title: '待核对日期', message: '日期需确认' }] }) })
  await tick()
  assert.equal(state.canApply.value, false)
  state.allowWarnings.value = true
  assert.equal(state.canApply.value, true)
  state.selectChange(state.preview.value.changes[0], false)
  assert.equal(state.allowWarnings.value, false)
  assert.equal(state.canApply.value, false)
})

test('非管理员、规则失败或选中记录错误都不可提交', async t => {
  for (const options of [
    { props: { admin: false } },
    { preview: async () => preview(undefined, { validation: { status: 'failed', error: '规则服务不可用' } }) },
    { preview: async () => preview(undefined, { issues: [{ level: 'error', section: 'wbs', title: '关联缺失', message: '缺少父节点' }] }) },
  ]) {
    const { state, applyCalls } = review(t, options)
    await tick()
    assert.equal(state.canApply.value, false)
    await state.apply()
    assert.equal(applyCalls.length, 0)
  }
})

test('部分提交后保留未选项为未选，展示已提交项与余项，不清空剩余草稿', async t => {
  let saved = false
  const { state, applyCalls, applied } = review(t, {
    preview: async (_pid, _did, input) => saved ? preview([change('wbs:1', 'applied'), change('wbs:2')], { preview_id: 'remaining', selected_keys: input.selected_keys }) : preview(undefined, { selected_keys: ['wbs:1'] }),
    apply: async () => { saved = true; return { result: { status: 'partially_applied', counts: { wbs: 1 } } } },
  })
  await tick()
  await state.apply()
  assert.equal(applied(), 1)
  assert.equal(applyCalls[0][2].preview_id, 'preview-1')
  assert.equal(state.preview.value.preview_id, 'remaining')
  assert.deepEqual(state.selectedKeys.value, [])
  assert.equal(state.preview.value.changes[1].key, 'wbs:2')
  assert.match(state.notice.value, /已提交 1 项/)
  assert.equal(state.canApply.value, false)
})

test('提交遇到数据冲突后禁用旧预览，只有重新核对后才能继续', async t => {
  const { state, calls, applyCalls } = review(t, { apply: async () => { throw { isAxiosError: true, response: { status: 409, data: { detail: 'stale' } } } } })
  await tick()
  await state.apply()
  assert.equal(state.stale.value, true)
  assert.equal(state.canApply.value, false)
  assert.match(state.error.value, /重新获取差异/)
  await state.apply()
  assert.equal(applyCalls.length, 1)
  assert.equal(calls.length, 1)
  await state.refresh()
  assert.equal(state.canApply.value, true)
})

test('预览加载失败可重试，关闭弹窗取消请求且忽略迟到结果', async t => {
  let attempt = 0
  const late = deferred()
  const { state, props, calls } = review(t, { preview: async () => { attempt++; if (attempt === 1) throw new Error('读取失败'); return late.promise } })
  await tick()
  assert.equal(state.loading.value, false)
  assert.match(state.error.value, /读取失败/)
  const pending = state.refresh()
  props.open = false
  assert.equal(calls[1][3].aborted, true)
  late.resolve(preview())
  await pending
  assert.equal(state.preview.value, null)
  assert.equal(state.canApply.value, false)
})

test('草稿修订会即时废弃当前确认，重新预览前不可提交', async t => {
  const later = deferred()
  let request = 0
  const { state, props } = review(t, { preview: async () => ++request === 1 ? preview() : later.promise })
  await tick()
  props.draft.revision = 2
  assert.equal(state.stale.value, true)
  assert.equal(state.canApply.value, false)
  later.resolve(preview(undefined, { draft_revision: 2, preview_id: 'revision-2' }))
  await tick()
  assert.equal(state.preview.value.draft_revision, 2)
  assert.equal(state.canApply.value, true)
})

test('后台轮询返回同一草稿对象的新副本时不重置用户选择与凭据', async t => {
  const { state, props, calls } = review(t, { preview: async (_pid, _did, input) => preview(undefined, { selected_keys: input.selected_keys ?? ['wbs:1', 'wbs:2'] }) })
  await tick()
  state.selectChange(state.preview.value.changes[0], false)
  await tick()
  const count = calls.length
  props.draft = { ...props.draft }
  await tick()
  assert.equal(calls.length, count)
  assert.deepEqual(state.selectedKeys.value, ['wbs:2'])
  props.draft = { ...props.draft, revision: 2 }
  await tick()
  assert.deepEqual(calls.at(-1)[2].selected_keys, ['wbs:2'])
})

test('新人员账号与密码校验影响提交，刷新预览保留已修改凭据', async t => {
  const required = [
    { identity_card_no: '110001', real_name: '张珂', position_name: '项目经理', suggested_username: 'zhangke' },
    { identity_card_no: '110002', real_name: '李雯', position_name: '安全员', suggested_username: 'liwen' },
  ]
  const { state, applyCalls } = review(t, { preview: async () => preview(undefined, { required_personnel_credentials: required }) })
  await tick()
  assert.equal(state.credentials.value[0].username, 'zhangke')
  state.credentials.value[0].username = 'liwen'
  assert.equal(state.canApply.value, false)
  assert.match(state.credentialErrors.value[0], /重复/)
  state.credentials.value[0].username = 'manager.zhang'
  state.credentials.value[0].initial_password = 'short'
  assert.equal(state.canApply.value, false)
  state.credentials.value[0].initial_password = 'Safe1234!'
  await state.refresh()
  assert.equal(state.credentials.value[0].username, 'manager.zhang')
  assert.equal(state.credentials.value[0].initial_password, 'Safe1234!')
  await state.apply()
  assert.deepEqual(applyCalls[0][2].personnel_credentials[0], { identity_card_no: '110001', username: 'manager.zhang', initial_password: 'Safe1234!' })
})

test('分区、关键词与变化筛选相交；对比保留未修改字段且不暴露内部标识', () => {
  const changes = [change('工程经理', 'update', 'personnel'), change('分部工程', 'add'), change('已归档', 'applied'), change('一致记录', 'unchanged')]
  assert.deepEqual(presentation.filterInitializationChanges(changes, 'wbs', 'changes', '工程').map(item => item.key), ['分部工程'])
  assert.deepEqual(presentation.filterInitializationChanges(changes, 'all', 'applied', '').map(item => item.key), ['已归档'])
  const comparison = presentation.initializationComparisonFields(change('x', 'update', 'wbs', { before: { id: 8, name: '旧名称', level: 0 }, after: { record_id: 12, name: '新名称', level: 0 }, fields: [{ name: 'name', before: '旧名称', after: '新名称' }] }))
  assert.deepEqual(comparison.map(item => item.name), ['name', 'level'])
  assert.equal(comparison[0].changed, true)
  assert.equal(comparison[1].changed, false)
  assert.equal(presentation.formatInitializationChangeValue(0), '0')
  assert.equal(presentation.formatInitializationChangeValue(false), '否')
  assert.equal(presentation.formatInitializationChangeValue(null), '未填写')
})

test('工程字段分别显示字段名称和单字段差异，不把完整工程原值重复为多条资料', () => {
  const item = change('17:contract_duration_days', 'update', 'project', {
    title: '工程信息', before: { name: '管廊工程', contract_duration_days: 365, engineering_type_description: '原工程概况' },
    after: { name: '管廊工程', contract_duration_days: 420, engineering_type_description: '原工程概况' },
    fields: [{ name: 'contract_duration_days', before: 365, after: 420 }],
  })
  assert.equal(presentation.initializationChangeTitle(item), '合同工期（天）')
  assert.deepEqual(presentation.initializationComparisonFields(item).map(field => field.name), ['contract_duration_days'])
  assert.equal(presentation.filterInitializationChanges([item], 'project', 'changes', '工程概况').length, 0)
  assert.equal(presentation.filterInitializationChanges([item], 'project', 'changes', '工期').length, 1)
  item.operation = 'applied'; item.fields = []
  assert.deepEqual(presentation.initializationComparisonFields(item).map(field => field.name), ['contract_duration_days'])
})

test('取消请求与业务错误分别归一化，密码包含四类字符且长度受限', () => {
  assert.equal(initializationChangeError({ __CANCEL__: true }).cancelled, true)
  assert.equal(initializationChangeError({ isAxiosError: true, response: { status: 422, data: { detail: { message: '关联工序不存在' } } } }).message, '关联工序不存在')
  for (const length of [4, 8, 12, 30]) {
    const password = presentation.generateInitializationPassword(length)
    assert.equal(password.length, Math.min(12, Math.max(8, length)))
    assert.match(password, /[A-Z]/); assert.match(password, /[a-z]/); assert.match(password, /[0-9]/); assert.match(password, /[!@#$%&*]/)
  }
})
