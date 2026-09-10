import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { createServer } from 'vite'
import { effectScope, reactive, nextTick } from 'vue'
import { fileURLToPath } from 'node:url'
const mocks = {
  '@/api/client': 'export default { get: (...args) => globalThis.__homeChat.api.get(...args), post: (...args) => globalThis.__homeChat.api.post(...args) }',
  '@/api/agentStream': 'export const streamAgentConversationMessage = (...args) => globalThis.__homeChat.stream(...args); export const streamAgentConversationConfirmation = async () => {}',
  '@/stores/app': 'export const useAppStore = () => globalThis.__homeChat.store',
  '@/composables/useAsyncConfirmDialog': 'export const useAsyncConfirmDialog = () => ({ confirmAsyncAction() {} })',
  'vue-router': 'export const useRoute = () => globalThis.__homeChat.route; export const useRouter = () => ({ replace: async () => {} })',
  'naive-ui': 'export const useMessage = () => globalThis.__homeChat.message',
}
const server = await createServer({
  configFile: false,
  resolve: { alias: [
    ...Object.keys(mocks).map(id => ({ find: id, replacement: '\0home-chat:' + id })),
    { find: '@', replacement: fileURLToPath(new URL('../src', import.meta.url)) },
  ] },
  server: { middlewareMode: true }, appType: 'custom', logLevel: 'error',
  plugins: [{
    name: 'home-chat-fixture', enforce: 'pre',
    resolveId(id) {
      if (id.startsWith('\0home-chat:')) return id
      if (id in mocks) return '\0home-chat:' + id
    },
    load(id) { if (id.startsWith('\0home-chat:')) return mocks[id.slice(11)] },
  }],
})
after(async () => { await server.close(); delete globalThis.__homeChat })
const { useHomeAgentConversations } = await server.ssrLoadModule('/src/composables/useHomeAgentConversations.ts')
const envelope = data => ({ data: { data } })
const conversation = { id: 12, project_id: 1, conversation_type: 'general', agent_id: 'main', agent_name: 'Dobby', title: '你好', status: 'active' }
function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
async function fixture(t) {
  const state = globalThis.__homeChat = {
    api: { get: async url => envelope(url === '/agents/catalog' ? { business_agents: [] } : []), post: async () => envelope(conversation) },
    store: reactive({ currentProjectId: '1', uploadAttachment: async () => {}, addLog() {} }),
    route: reactive({ path: '/workbench', query: { mode: 'quick' } }),
    message: { warning() {}, error() {}, info() {} }, streamCalls: 0,
    stream: async () => { state.streamCalls++; throw new Error('stream fixture finished') },
  }
  const scope = effectScope(), chat = scope.run(useHomeAgentConversations)
  t.after(() => scope.stop())
  await new Promise(resolve => setImmediate(resolve))
  return { state, chat }
}
test('创建会话仍在等待时，用户消息已经显示且输入框已清空', async t => {
  const { state, chat } = await fixture(t), pending = deferred()
  state.api.post = () => pending.promise
  chat.quickCommand.value = '你好'
  const sending = chat.dispatchQuickCommand()
  assert.equal(chat.homeQuickChatMessages.value[0].content, '你好')
  assert.equal(chat.quickCommand.value, '')
  assert.ok(chat.homeQuickStreamingTrace.value)
  await nextTick()
  assert.equal(chat.quickUploading.value, true)
  assert.equal(state.streamCalls, 0)
  assert.equal(await chat.dispatchQuickCommand(), false)
  pending.resolve(envelope(conversation)); await sending
  assert.equal(state.streamCalls, 1)
})
test('上传附件前即显示消息，失败恢复原草稿和附件', async t => {
  const { state, chat } = await fixture(t), pending = deferred()
  const file = { name: '施工资料.pdf', size: 100, lastModified: 1, type: 'application/pdf' }
  state.store.uploadAttachment = () => pending.promise
  chat.quickCommand.value = '分析资料'; chat.quickFiles.value = [file]
  const sending = chat.dispatchQuickCommand()
  assert.equal(chat.homeQuickChatMessages.value[0].attachments[0].name, file.name)
  assert.equal(chat.quickFiles.value.length, 0)
  await nextTick(); pending.reject(new Error('上传失败')); await sending
  assert.equal(chat.quickCommand.value, '分析资料')
  assert.equal(chat.quickFiles.value[0].name, file.name)
  assert.equal(chat.homeQuickChatMessages.value.length, 0)
  assert.equal(chat.quickUploading.value, false)
})
test('准备失败不会覆盖用户新输入的下一条草稿', async t => {
  const { state, chat } = await fixture(t), pending = deferred()
  state.api.post = () => pending.promise
  chat.quickCommand.value = '第一条'
  const sending = chat.dispatchQuickCommand()
  await nextTick(); chat.quickCommand.value = '第二条'
  pending.reject(new Error('创建失败')); await sending
  assert.equal(chat.quickCommand.value, '第二条')
  assert.match(chat.homeQuickChatMessages.value[0].sendError, /未发送成功/)
})
test('首条消息尚未建立会话时也能停止，不会再请求模型', async t => {
  const { state, chat } = await fixture(t)
  state.api.post = (_url, _body, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(signal.reason), { once: true })
  })
  chat.quickCommand.value = '停止测试'
  const sending = chat.dispatchQuickCommand()
  await nextTick(); await nextTick(); await chat.stopHomeAgent(); await sending
  assert.equal(state.streamCalls, 0)
  assert.equal(chat.quickUploading.value, false)
  assert.equal(chat.quickCommand.value, '停止测试')
})
test('切换项目后旧请求不能恢复旧消息或清除新请求的停止控制器', async t => {
  const { state, chat } = await fixture(t), old = deferred(), current = deferred()
  state.api.post = () => old.promise
  chat.quickCommand.value = '旧项目'
  const first = chat.dispatchQuickCommand(); await nextTick()
  state.store.currentProjectId = '2'
  await new Promise(resolve => setImmediate(resolve))
  state.api.post = (_url, _body, { signal }) => {
    signal.addEventListener('abort', () => current.reject(signal.reason), { once: true })
    return current.promise
  }
  chat.quickCommand.value = '新项目'
  const second = chat.dispatchQuickCommand(); await nextTick(); await nextTick()
  old.resolve(envelope(conversation)); await first
  assert.equal(chat.homeAgentConversation.value, null)
  assert.equal(chat.homeQuickChatMessages.value[0].content, '新项目')
  assert.equal(chat.quickUploading.value, true)
  await chat.stopHomeAgent(); await second
  assert.equal(state.streamCalls, 0)
})

test('本次选中图片原数据随对话发送，资料上传保留且后续消息不夹带旧图片', async t => {
  const { state, chat } = await fixture(t), uploads = [], requests = []
  const image = { name: '现场.png', size: 4, lastModified: 1, type: 'image/png', arrayBuffer: async () => Uint8Array.from([1, 2, 3, 4]).buffer }
  const document = { name: '说明.pdf', size: 100, lastModified: 2, type: 'application/pdf' }
  state.store.uploadAttachment = async file => { uploads.push(file.name) }
  state.stream = async (_id, _content, handlers, _signal, extras) => {
    requests.push(extras)
    handlers.onDone({ message: { id: 40, content: '已收到', extra_data: {} }, runtime_status: 'completed' })
  }
  chat.quickCommand.value = '分析本次图片'; chat.quickFiles.value = [image, document]
  await chat.dispatchQuickCommand()
  assert.deepEqual(uploads, ['现场.png', '说明.pdf'])
  assert.deepEqual(requests[0], { image_attachments: [{ name: '现场.png', media_type: 'image/png', data: 'AQIDBA==' }] })
  chat.quickCommand.value = '继续说明'; chat.quickFiles.value = []
  await chat.dispatchQuickCommand()
  assert.deepEqual(requests[1], {})
})
