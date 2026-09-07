import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { effectScope, ref } from 'vue'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom', logLevel: 'error' })
after(() => server.close())
const { default: api } = await server.ssrLoadModule('/src/api/client.ts')
const { useChatTitleValidation } = await server.ssrLoadModule('/src/composables/useChatTitleValidation.ts')
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { resolve, reject, promise } }
const response = available => ({ data: { data: { available } } })
function fixture(t) {
  const scope = effectScope(), title = ref('资料组'), project = ref('1'), enabled = ref(true)
  t.after(() => scope.stop())
  return { scope, title, project, enabled, ...scope.run(() => useChatTitleValidation(title, () => project.value, () => 7, () => enabled.value)) }
}

test('输入不自动请求，失焦调用时显示 loading，完成后提示重名并排除正在编辑的群', async t => {
  const state = fixture(t), pending = deferred(), calls = []
  api.post = (...args) => { calls.push(args); return pending.promise }
  state.title.value = '  新名称  '
  assert.equal(calls.length, 0)
  const checking = state.check()
  assert.equal(state.checking.value, true)
  assert.equal(calls[0][0], '/projects/1/chat/check-title')
  assert.deepEqual(calls[0][1], { title: '新名称', exclude_channel_id: 7 })
  pending.resolve(response(false)); await checking
  assert.equal(state.checking.value, false)
  assert.match(state.error.value, /同名/)
  state.title.value = '再次修改'
  assert.equal(state.error.value, '')
})

test('旧检测晚返回不能覆盖新名称结果，也不能停止新请求的 loading', async t => {
  const state = fixture(t), old = deferred(), current = deferred()
  api.post = () => old.promise
  const first = state.check()
  state.title.value = '另一个群'
  api.post = () => current.promise
  const second = state.check()
  old.resolve(response(false)); await first
  assert.equal(state.checking.value, true)
  assert.equal(state.error.value, '')
  current.resolve(response(true)); await second
  assert.equal(state.checking.value, false)
  assert.equal(state.error.value, '')
})

test('切换项目、关闭弹窗或卸载均取消检测并忽略旧响应', async t => {
  for (const action of ['project', 'close', 'dispose']) {
    const state = fixture(t), pending = deferred()
    let signal
    api.post = (_url, _body, options) => { signal = options.signal; return pending.promise }
    const checking = state.check()
    if (action === 'project') state.project.value = '2'
    else if (action === 'close') state.enabled.value = false
    else state.scope.stop()
    assert.equal(signal.aborted, true)
    pending.resolve(response(false)); await checking
    assert.equal(state.error.value, '')
    assert.equal(state.checking.value, false)
  }
})

test('检测失败可通过再次失焦重试，空名称不发送请求', async t => {
  const state = fixture(t)
  api.post = async () => { throw new Error('offline') }
  await state.check()
  assert.match(state.error.value, /检测失败/)
  api.post = async () => response(true)
  await state.check()
  assert.equal(state.error.value, '')
  state.title.value = ' '
  api.post = () => { throw new Error('不应请求') }
  await state.check()
  assert.equal(state.error.value, '群名称不能为空')
  assert.equal(state.checking.value, false)
})
