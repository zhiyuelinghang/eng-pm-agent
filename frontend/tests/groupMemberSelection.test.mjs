import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { effectScope, ref } from 'vue'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom', logLevel: 'error' })
after(() => server.close())
const { useGroupMemberSelection } = await server.ssrLoadModule('/src/composables/useGroupMemberSelection.ts')

function selection(t, ids = [2, 3, 4]) {
  const scope = effectScope()
  t.after(() => scope.stop())
  const members = ref(ids), selected = ref([])
  return { members, selected, ...scope.run(() => useGroupMemberSelection(members, selected)) }
}

test('全选涵盖完整项目名单；只全选仍创建普通群', t => {
  const state = selection(t, Array.from({ length: 25 }, (_, i) => i + 2))
  state.allParticipantsSelected.value = true
  assert.deepEqual(state.selected.value, state.members.value)
  assert.equal(state.allGroupMembers.value, false)
  state.autoSyncMembers.value = true
  assert.equal(state.allGroupMembers.value, true)
  state.autoSyncMembers.value = false
  assert.equal(state.allGroupMembers.value, false)
  assert.equal(state.selected.value.length, 25)
})

test('逐一选满也可以启用自动同步；取消任一成员即取消 ALL 和同步', t => {
  const state = selection(t)
  state.selected.value = [2, 3]
  assert.equal(state.someParticipantsSelected.value, true)
  assert.equal(state.allParticipantsSelected.value, false)
  state.selected.value.push(4)
  assert.equal(state.allParticipantsSelected.value, true)
  state.autoSyncMembers.value = true
  assert.equal(state.allGroupMembers.value, true)
  state.selected.value = [2, 4]
  assert.equal(state.allGroupMembers.value, false)
  assert.equal(state.autoSyncMembers.value, false)
  state.allParticipantsSelected.value = true
  assert.equal(state.allGroupMembers.value, false)
})

test('取消全选清空名单和自动同步，空名单不误判为 ALL', t => {
  const state = selection(t)
  state.allParticipantsSelected.value = true
  state.autoSyncMembers.value = true
  state.allParticipantsSelected.value = false
  assert.deepEqual(state.selected.value, [])
  assert.equal(state.autoSyncMembers.value, false)
  state.members.value = []
  assert.equal(state.allParticipantsSelected.value, false)
  assert.equal(state.someParticipantsSelected.value, false)
  assert.equal(state.allGroupMembers.value, false)
})
