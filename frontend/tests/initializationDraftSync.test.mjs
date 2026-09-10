import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { effectScope, ref } from 'vue'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom', logLevel: 'error' })
after(() => server.close())
const { useInitializationDraftSync } = await server.ssrLoadModule('/src/composables/useInitializationDraftSync.ts')
const { getConversationInitializationDraft } = await server.ssrLoadModule('/src/api/initializationChanges.ts')
const { default: api } = await server.ssrLoadModule('/src/api/client.ts')
const wait = (ms = 10) => new Promise(resolve => setTimeout(resolve, ms))
async function waitFor(predicate) {
  const deadline = Date.now() + 1000
  while (!predicate() && Date.now() < deadline) await wait()
  assert.ok(predicate(), '状态应在超时前完成更新')
}
function deferred() { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
const draft = (conversation_id = 21, revision = 1, project_id = 7) => ({ id: conversation_id * 10, project_id, conversation_id, revision })
function synchronization(t, options = {}) {
  const scope = effectScope()
  t.after(() => scope.stop())
  const projectId = ref('7'), conversationId = ref(options.conversationId ?? 21), running = ref(options.running ?? false)
  const calls = [], changes = [], errors = []
  const state = scope.run(() => useInitializationDraftSync({ projectId, conversationId, running, onChange: (...args) => changes.push(args), onError: error => errors.push(error) }, {
    pollMs: options.pollMs ?? 20,
    load: async (...args) => { calls.push(args); return options.load ? options.load(...args) : draft(args[1], calls.length, Number(args[0])) },
  }))
  return { scope, state, projectId, conversationId, running, calls, changes, errors }
}

test('读取草稿显式传递当前会话参数，没有会话时不读取项目全局草稿', async t => {
  const original = api.defaults.adapter
  globalThis.sessionStorage ??= { getItem: () => null }
  t.after(() => { api.defaults.adapter = original })
  let requested
  api.defaults.adapter = async config => { requested = config; return { status: 200, statusText: 'OK', headers: {}, config, data: { data: draft() } } }
  await getConversationInitializationDraft('7', 21)
  assert.equal(requested.params.conversation_id, 21)
  assert.match(requested.url, /projects\/7\/initialization-drafts\/latest$/)
  const { state, conversationId, calls } = synchronization(t, { conversationId: 0 })
  assert.equal(calls.length, 0)
  conversationId.value = 21
  await wait()
  assert.equal(state.draft.value.conversation_id, 21)
})

test('切换历史会话立即清空旧草稿并忽略已取消请求的迟到响应', async t => {
  const old = deferred()
  const { state, conversationId, calls } = synchronization(t, { load: async (_project, conversation) => conversation === 21 ? old.promise : draft(conversation) })
  conversationId.value = 22
  assert.equal(calls[0][2].aborted, true)
  assert.equal(state.draft.value, null)
  await wait()
  assert.equal(state.draft.value.conversation_id, 22)
  old.resolve(draft(21))
  await wait()
  assert.equal(state.draft.value.conversation_id, 22)
})

test('新会话清除草稿并停止轮询，旧会话响应不能重新出现', async t => {
  const { state, conversationId, calls } = synchronization(t, { running: true })
  await wait()
  assert.ok(state.draft.value)
  conversationId.value = null
  const count = calls.length
  assert.equal(state.draft.value, null)
  await wait(55)
  assert.equal(calls.length, count)
})

test('后端返回其他会话或其他项目的草稿时不展示', async t => {
  const a = synchronization(t, { load: async () => draft(99) })
  const b = synchronization(t, { load: async () => draft(21, 1, 88) })
  await wait()
  assert.equal(a.state.draft.value, null)
  assert.equal(b.state.draft.value, null)
})

test('生成过程中周期读取已完成分区，结束或卸载后不再轮询', async t => {
  const { state, scope, running, calls } = synchronization(t, { running: true, pollMs: 12 })
  await wait(55)
  assert.ok(calls.length >= 2)
  assert.ok(state.draft.value.revision >= 2)
  running.value = false
  const stopped = calls.length
  await wait(35)
  assert.equal(calls.length, stopped)
  running.value = true
  scope.stop()
  const unmounted = calls.length
  await wait(35)
  assert.equal(calls.length, unmounted)
})

test('轮询等待上一请求完成，失败后可恢复且不打断正在生成的对话', async t => {
  let request = 0, active = 0, maximum = 0
  const { state, calls, errors } = synchronization(t, { running: true, pollMs: 8, load: async () => {
    active++; maximum = Math.max(maximum, active); request++
    await wait(18)
    active--
    if (request === 2) throw new Error('临时读取失败')
    return draft(21, request)
  } })
  await waitFor(() => state.draft.value?.revision >= 3)
  assert.ok(calls.length >= 3)
  assert.equal(maximum, 1)
  assert.equal(errors.length, 0)
  assert.ok(state.draft.value.revision >= 3)
})
