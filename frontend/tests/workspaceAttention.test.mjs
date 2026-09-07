import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'
import { createPinia, setActivePinia } from 'pinia'

globalThis.__attentionApi = { get: async () => ({ data: { data: { channels: {} } } }), post: async () => ({}) }
const server = await createServer({
  server: { middlewareMode: true }, appType: 'custom', logLevel: 'error',
  plugins: [{
    name: 'attention-api-fixture', enforce: 'pre',
    resolveId(id) { if (id === '@/api/client' || /\/src\/api\/client(?:\.ts)?$/.test(id.replaceAll('\\', '/'))) return '\0attention-api' },
    load(id) { if (id === '\0attention-api') return 'export default { get: (...args) => globalThis.__attentionApi.get(...args), post: (...args) => globalThis.__attentionApi.post(...args) }' },
  }],
})
after(async () => { delete globalThis.__attentionApi; await server.close() })
const { useChatUnreadStore } = await server.ssrLoadModule('/src/stores/chatUnread.ts')
const envelope = channels => ({ data: { data: { channels } } })
function store() { setActivePinia(createPinia()); return useChatUnreadStore() }
function deferred() { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }

test('切换工程后忽略旧工程延迟返回的未读计数', async () => {
  const unread = store(), first = deferred()
  globalThis.__attentionApi.get = url => url.includes('/projects/1/') ? first.promise : Promise.resolve(envelope({ 20: 3 }))
  const old = unread.refresh('1')
  await unread.refresh('2')
  first.resolve(envelope({ 10: 9 })); await old
  assert.equal(unread.projectId, '2'); assert.equal(unread.total, 3); assert.deepEqual(unread.counts, { 20: 3 })
})
test('退出登录清空计数，旧请求不会恢复前一账号的数据', async () => {
  const unread = store(), response = deferred()
  globalThis.__attentionApi.get = () => response.promise
  const pending = unread.refresh('1'); unread.reset()
  response.resolve(envelope({ 10: 9 })); await pending
  assert.equal(unread.total, 0); assert.equal(unread.projectId, '')
})
test('未读消息和本人待办、任务数量分别保存', async () => {
  const unread = store()
  globalThis.__attentionApi.get = async url => url.endsWith('/my-task-counts')
    ? { data: { data: { tasks: 4, home_todo: 2 } } } : envelope({ 10: 8, 11: 2 })
  await unread.refresh('1'); await unread.refreshTasks('1')
  assert.equal(unread.total, 10); assert.deepEqual(unread.taskCounts, { tasks: 4, home_todo: 2 })
})
test('已读回执只提交已展示消息的位置，回读服务器计数保留后到消息', async () => {
  const unread = store(), posts = []
  globalThis.__attentionApi.get = async () => envelope({ 10: 3 })
  await unread.refresh('1')
  globalThis.__attentionApi.post = async (url, payload) => { posts.push([url, payload]) }
  globalThis.__attentionApi.get = async () => envelope({ 10: 1 })
  await unread.markRead('1', 10, 100)
  assert.deepEqual(posts, [['/chat/channels/10/read', { message_id: 100 }]])
  assert.equal(unread.total, 1)
})
