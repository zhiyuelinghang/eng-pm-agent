<template>
  <div class="group-settings" :class="{ 'is-compact': compact }">
    <template v-if="compact">
      <div class="group-sidebar-actions">
        <button type="button" class="group-settings-button" @click="dialog = 'files'">群文件</button>
        <n-dropdown trigger="click" placement="bottom-end" :options="menuOptions" @select="openAction"><button type="button" class="group-settings-button" aria-label="群设置" aria-haspopup="menu">群设置</button></n-dropdown>
      </div>
    </template>
    <template v-else>
      <div class="group-panel-tabs" role="tablist" aria-label="群信息">
        <button :id="`${titleInputId}-settings-tab`" type="button" role="tab" :aria-selected="view === 'settings'" :aria-controls="`${titleInputId}-pane`" :tabindex="view === 'settings' ? 0 : -1" @click="view = 'settings'" @keydown="onTabKey($event, 'files')">群设置</button>
        <button :id="`${titleInputId}-files-tab`" type="button" role="tab" :aria-selected="view === 'files'" :aria-controls="`${titleInputId}-pane`" :tabindex="view === 'files' ? 0 : -1" @click="view = 'files'" @keydown="onTabKey($event, 'settings')">群文件</button>
      </div>
      <div :id="`${titleInputId}-pane`" class="group-panel-content" role="tabpanel" :aria-labelledby="`${titleInputId}-${view}-tab`">
        <template v-if="view === 'settings'">
          <div class="group-name-row"><span>群名称</span><button v-if="canManage" type="button" class="group-edit-name" aria-label="修改群名称" @click="openAction('rename')"><n-icon :size="16"><Pencil /></n-icon><span>修改</span></button></div>
          <p class="group-current-name">{{ channel.title }}</p>
          <div class="group-members-heading"><h3>群成员 <span>{{ members.length }}</span></h3><button type="button" class="group-edit-name" @click="openAction('members')">{{ canManage ? '管理' : '查看全部' }}<n-icon :size="15"><ChevronRight /></n-icon></button></div><p v-if="isAll" class="group-sync-label">ALL · 成员随项目名单自动同步</p>
          <div class="group-sidebar-members">
            <div v-for="member in members" :key="member.user_id" class="group-person">
              <span class="group-person-avatar">{{ member.name.slice(-1) }}</span>
              <div><strong>{{ member.name }}<small v-if="member.user_id === currentUserId">我</small></strong></div>
              <span v-if="member.member_role === 'owner'" class="group-owner">群主</span>
            </div>
          </div>
        </template>
        <template v-else>
          <div class="group-file-toolbar"><div class="group-file-heading"><n-icon :size="19"><Folder /></n-icon><strong>全部文件</strong><span v-if="!fileLoading && !fileError" class="group-file-count">{{ files.length }}{{ nextCursor ? '+' : '' }}</span></div><ChatGroupFileUpload :channel-id="channel.id" label="上传文件" prominent @uploaded="fileUploaded" /></div>
          <p v-if="fileLoading && !files.length" class="group-empty" role="status">正在加载群文件…</p>
          <div v-else-if="fileError" class="group-empty" role="status"><p>{{ fileError }}</p><button type="button" class="group-small-button" @click="loadFiles()">重试</button></div>
          <div v-else-if="!files.length" class="group-empty"><n-icon :size="32"><Folder /></n-icon><p>暂无群文件</p></div>
          <button v-for="file in files" :key="file.id" type="button" class="group-file" :disabled="Boolean(downloading)" :title="`下载 ${file.file_name}`" @click="downloadFile(file)">
            <n-icon :size="22"><Folder /></n-icon><span><strong>{{ downloading === file.id ? '下载中…' : file.file_name }}</strong><small>{{ fileSize(file.file_size) }}<time v-if="file.created_at">{{ fileDate(file.created_at) }}</time></small></span>
          </button>
          <button v-if="nextCursor" type="button" class="group-small-button group-more" :disabled="fileLoading" @click="loadFiles(true)">{{ fileLoading ? '加载中…' : '加载更多' }}</button>
        </template>
      </div>
    </template>

    <n-modal :show="dialog !== null" :auto-focus="false" :mask-closable="!busy" :close-on-esc="!busy" @after-enter="focusTitle" @update:show="value => { if (!value && !busy) dialog = null }">
      <!-- VFocusTrap 依赖 DIV 根节点定位弹窗，确保群名称输入框可正常获得焦点。 -->
      <div class="group-editor" :class="{ 'group-editor-wide': dialog === 'files', 'group-editor-members': dialog === 'members' }" role="dialog" aria-modal="true" :aria-labelledby="editorTitleId">
        <header class="group-editor-heading"><h2 :id="editorTitleId">{{ dialogTitle }}</h2><button type="button" class="group-close" :disabled="busy" aria-label="关闭弹窗" @click="dialog = null"><n-icon :size="20"><X /></n-icon></button></header>
        <form v-if="dialog === 'rename'" class="group-settings-form" @submit.prevent="saveTitle">
          <div class="group-editor-body">
            <label :for="titleInputId" class="group-field-label">群名称</label>
            <div class="chat-title-field">
              <input :id="titleInputId" ref="titleInput" v-model="title" maxlength="100" :disabled="busy" required :aria-invalid="Boolean(titleError)" :aria-describedby="titleError ? `${titleInputId}-error` : undefined" @blur="checkTitle">
              <span v-if="checkingTitle" class="chat-title-loading" role="status" aria-label="正在检测群名称"></span>
            </div>
            <p v-if="titleError" :id="`${titleInputId}-error`" class="chat-title-error" role="alert">{{ titleError }}</p>
          </div>
          <footer><button type="button" class="group-small-button" :disabled="busy" @click="dialog = null">取消</button><button type="submit" class="group-primary-button" :disabled="busy || Boolean(titleError) || !title.trim() || title.trim() === channel.title">{{ busy ? '保存中…' : '保存' }}</button></footer>
        </form>
        <div v-else-if="dialog === 'files'" class="group-editor-body group-files-body">
          <div class="group-file-toolbar"><div class="group-file-heading"><n-icon :size="19"><Folder /></n-icon><strong>全部文件</strong><span v-if="!fileLoading && !fileError" class="group-file-count">{{ files.length }}{{ nextCursor ? '+' : '' }}</span></div><ChatGroupFileUpload :channel-id="channel.id" label="上传文件" prominent @uploaded="fileUploaded" /></div>
          <p v-if="fileLoading && !files.length" class="group-empty" role="status">正在加载群文件…</p>
          <div v-else-if="fileError" class="group-empty" role="status"><p>{{ fileError }}</p><button type="button" class="group-small-button" @click="loadFiles()">重试</button></div>
          <div v-else-if="!files.length" class="group-empty"><n-icon :size="32"><Folder /></n-icon><p>暂无群文件</p></div>
          <button v-for="file in files" :key="file.id" type="button" class="group-file" :disabled="Boolean(downloading)" :title="`下载 ${file.file_name}`" @click="downloadFile(file)">
            <n-icon :size="22"><Folder /></n-icon><span><strong>{{ downloading === file.id ? '下载中…' : file.file_name }}</strong><small>{{ fileSize(file.file_size) }}<time v-if="file.created_at">{{ fileDate(file.created_at) }}</time></small></span>
          </button>
          <button v-if="nextCursor" type="button" class="group-small-button group-more" :disabled="fileLoading" @click="loadFiles(true)">{{ fileLoading ? '加载中…' : '加载更多' }}</button>
        </div>
        <template v-else>
          <div class="group-editor-body">
            <GroupMemberTable v-model:selected-ids="selectedIds" v-model:search="memberSearch" :rows="managementRows" label="群成员" :selectable="canManage" show-role :current-user-id="currentUserId" :locked-ids="[currentUserId]" :loading="peopleLoading" :error="peopleError" :disabled="busy">
              <template #toolbar>
                <strong>选择参与人</strong><span>已选 {{ selectedIds.length }} 人</span>
                <label class="group-sync-choice" :title="allParticipantsSelected ? '自动同步后续项目人员变更' : '全选项目成员后可启用自动同步'"><input v-model="autoSyncMembers" type="checkbox" :disabled="!canManage || !allParticipantsSelected || peopleLoading || busy">自动同步</label>
                <span v-if="allGroupMembers" class="group-all-badge">ALL</span>
              </template>
              <template v-if="canManage" #actions="{ member }">
                <button v-if="member.user_id !== newOwnerId && selectedIds.includes(member.user_id) && members.some(row => row.user_id === member.user_id)" type="button" class="group-edit-name" :disabled="busy" @click="newOwnerId = member.user_id">设为群主</button>
                <span v-else class="group-member-muted">—</span>
              </template>
            </GroupMemberTable>
            <p class="group-members-note">{{ canManage ? '勾选添加成员，取消勾选移除成员；取消任一成员会关闭自动同步。保存后生效。' : '当前群的成员与自动同步设置。' }}</p>
            <p v-if="canManage" class="group-owner-note">当前群主保留在群内；转让群主后，由新群主管理。</p>
          </div>
          <footer class="group-members-footer">
            <button type="button" class="group-small-button" :disabled="busy" @click="dialog = null">{{ canManage ? '取消' : '关闭' }}</button>
            <button v-if="canManage" type="button" class="group-primary-button" :disabled="busy || peopleLoading || Boolean(peopleError) || !membershipChanged || !newOwnerId || !selectedIds.includes(newOwnerId)" @click="saveMembers">{{ busy ? '保存中…' : '保存更改' }}</button>
          </footer>
        </template>
      </div>
    </n-modal>
  </div>
</template>
<script setup lang="ts">
import { computed, getCurrentInstance, h, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NDropdown, NIcon, NModal, useMessage } from 'naive-ui'
import { ChevronRight, Folder, Pencil, Settings, Users, X } from '@vicons/tabler'
import api from '@/api/client'
import { listProjectChatParticipants, type ProjectChatChannel, type ProjectChatMember, type ProjectChatMessage, type ProjectChatParticipant } from '@/api/projectChat'
import { saveProjectChatMembership, updateProjectChatSettings, listProjectChatFiles, type ProjectChatFile } from '@/api/projectChatManagement'
import ChatGroupFileUpload from './ChatGroupFileUpload.vue'
import GroupMemberTable from './GroupMemberTable.vue'
import { useGroupMemberSelection } from '@/composables/useGroupMemberSelection'
import { useChatTitleValidation } from '@/composables/useChatTitleValidation'

const props = defineProps<{ channel: ProjectChatChannel; members: ProjectChatMember[]; currentUserId: number; projectId: string; compact?: boolean }>()
const emit = defineEmits<{ changed: [channel: ProjectChatChannel]; uploaded: [message: ProjectChatMessage] }>()
const titleInputId = `group-title-${getCurrentInstance()?.uid}`
const editorTitleId = `${titleInputId}-editor`
const notice = useMessage()
const view = ref<'settings' | 'files'>('settings')
const dialog = ref<'rename' | 'files' | 'members' | null>(null)
const titleInput = ref<HTMLInputElement | null>(null)
const isAll = computed(() => props.channel.all_members ?? props.channel.channel_type !== 'private')
const canManage = computed(() => props.members.some(member => member.user_id === props.currentUserId && member.member_role === 'owner'))
const memberSearch = ref('')
const title = ref(props.channel.title), busy = ref(false)
const { checking: checkingTitle, error: titleError, check: checkTitle } = useChatTitleValidation(
  title, () => props.projectId, () => props.channel.id, () => canManage.value && dialog.value === 'rename',
)
const newOwnerId = ref<number | null>(null)
const people = ref<ProjectChatParticipant[]>([]), selectedIds = ref<number[]>([]), peopleLoading = ref(false), peopleError = ref('')
const managementRows = computed(() => {
  const rows = canManage.value ? [...people.value] : [...props.members]
  if (canManage.value && !rows.some(row => row.user_id === props.currentUserId)) {
    const owner = props.members.find(member => member.user_id === props.currentUserId)
    if (owner) rows.push(owner)
  }
  return rows.map(row => ({ ...row, member_role: row.user_id === newOwnerId.value ? 'owner' : selectedIds.value.includes(row.user_id) ? 'member' : 'candidate' }))
})
const selectableIds = computed(() => managementRows.value.map(row => row.user_id))
const { autoSyncMembers, allParticipantsSelected, allGroupMembers } = useGroupMemberSelection(selectableIds, selectedIds)
const originalIds = ref<number[]>([]), originalSync = ref(false), originalOwner = ref<number | null>(null)
watch(selectedIds, ids => { if (newOwnerId.value && !ids.includes(newOwnerId.value)) newOwnerId.value = originalOwner.value }, { deep: true })
const membershipChanged = computed(() => autoSyncMembers.value !== originalSync.value || newOwnerId.value !== originalOwner.value || selectedIds.value.length !== originalIds.value.length || selectedIds.value.some(id => !originalIds.value.includes(id)))
let peopleSequence = 0
const files = ref<ProjectChatFile[]>([]), nextCursor = ref<number | null>(null), fileLoading = ref(false), fileError = ref(''), downloading = ref<number | null>(null)
let disposed = false, fileSequence = 0, fileController: AbortController | null = null
onBeforeUnmount(() => { disposed = true; fileController?.abort() })
watch(() => props.channel.title, value => { title.value = value })
watch(canManage, allowed => { if (!allowed && ['rename', 'members'].includes(dialog.value || '')) dialog.value = null })
watch([view, dialog, () => props.channel.last_message?.id], () => { if ((!props.compact && view.value === 'files') || dialog.value === 'files') void loadFiles() })
function errorText(error: any, fallback: string) { return error?.response?.data?.detail || fallback }
async function openMembers() {
  const sequence = ++peopleSequence
  dialog.value = 'members'; memberSearch.value = ''; peopleError.value = ''; peopleLoading.value = true
  selectedIds.value = props.members.map(member => member.user_id)
  newOwnerId.value = props.members.find(member => member.member_role === 'owner')?.user_id || null
  try {
    const rows = canManage.value ? await listProjectChatParticipants(props.projectId) : props.members
    if (disposed || sequence !== peopleSequence || dialog.value !== 'members') return
    people.value = rows
    originalIds.value = [...selectedIds.value]; originalOwner.value = newOwnerId.value
    autoSyncMembers.value = isAll.value; originalSync.value = isAll.value
  } catch (error) { if (!disposed && sequence === peopleSequence) peopleError.value = errorText(error, '项目成员加载失败，请关闭后重试。') }
  finally { if (!disposed && sequence === peopleSequence) peopleLoading.value = false }
}
async function mutate(action: () => Promise<ProjectChatChannel>, success: string) {
  if (busy.value || !canManage.value) return
  busy.value = true
  try { const channel = await action(); if (!disposed) { dialog.value = null; emit('changed', channel); notice.success(success); return true } }
  catch (error) { if (!disposed) notice.error(errorText(error, '群设置保存失败。')) }
  finally { if (!disposed) busy.value = false }
}
const dialogTitle = computed(() => ({ rename: '修改群名称', files: '群文件', members: canManage.value ? '管理群成员' : '群成员' })[dialog.value || 'members'])
const menuOptions = computed(() => {
  const icon = (component: typeof Settings) => () => h(NIcon, { size: 18 }, { default: () => h(component) })
  const options = []
  if (canManage.value) options.push({ label: '修改群名称', key: 'rename', icon: icon(Pencil) })
  options.push({ label: canManage.value ? '管理群成员' : '查看群成员', key: 'members', icon: icon(Users) })
  return options
})
function openAction(key: string) {
  if (busy.value) return
  if (key === 'members') { void openMembers(); return }
  if (key === 'rename' && canManage.value) { title.value = props.channel.title; dialog.value = key }
  if (key === 'files') dialog.value = key
}
async function onTabKey(event: KeyboardEvent, other: 'settings' | 'files') {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  view.value = event.key === 'Home' ? 'settings' : event.key === 'End' ? 'files' : other
  await nextTick()
  document.getElementById(`${titleInputId}-${view.value}-tab`)?.focus()
}
function focusTitle() { if (dialog.value === 'rename') titleInput.value?.focus() }
async function saveTitle() {
  if (titleError.value || !title.value.trim() || title.value.trim() === props.channel.title) return
  await mutate(() => updateProjectChatSettings(props.channel.id, title.value.trim()), '群名称已保存。')
}
async function saveMembers() {
  if (peopleLoading.value || peopleError.value || !newOwnerId.value || !membershipChanged.value) return
  await mutate(() => saveProjectChatMembership(props.channel.id, [...selectedIds.value], allGroupMembers.value, newOwnerId.value!), '成员设置已保存。')
}
async function loadFiles(more = false) {
  if (more && (fileLoading.value || !nextCursor.value)) return
  const sequence = ++fileSequence
  fileController?.abort(); fileController = new AbortController()
  fileLoading.value = true; fileError.value = ''
  try {
    const page = await listProjectChatFiles(props.channel.id, more ? nextCursor.value! : undefined, fileController.signal)
    if (disposed || sequence !== fileSequence) return
    files.value = more ? [...files.value, ...page.items] : page.items; nextCursor.value = page.next_cursor
  } catch (error) { if (!disposed && sequence === fileSequence) fileError.value = errorText(error, '群文件加载失败。') }
  finally { if (!disposed && sequence === fileSequence) fileLoading.value = false }
}
function fileUploaded(message: ProjectChatMessage) { emit('uploaded', message); void loadFiles() }
function fileSize(value: number) { return value >= 1048576 ? `${(value / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(value / 1024))} KB` }
function fileDate(value: string) { const date = new Date(value); return Number.isFinite(date.getTime()) ? date.toLocaleDateString('zh-CN') : '' }
async function downloadFile(file: ProjectChatFile) {
  if (downloading.value) return
  downloading.value = file.id
  try {
    const response = await api.get(`/projects/${props.projectId}/engineering-documents/knowledge/${encodeURIComponent(file.knowledge_id)}/download`, { responseType: 'blob' })
    if (disposed) return
    const url = URL.createObjectURL(response.data), link = document.createElement('a')
    link.href = url; link.download = file.file_name; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (error) { if (!disposed) notice.error(errorText(error, '文件下载失败。')) }
  finally { if (!disposed) downloading.value = null }
}
</script>
<style scoped>
.group-settings { display: flex; flex-direction: column; min-height: 0; flex: 1; min-width: 0; color: #193b3d; font-size: 14px; }
.group-settings.is-compact { padding: 0; }
.group-panel-tabs { display: flex; flex: 0 0 auto; gap: 24px; padding: 0 20px; border-bottom: 1px solid #e5ece8; }
.group-panel-tabs button { position: relative; padding: 18px 2px 16px; border: 0; background: transparent; color: #7a8b86; font: inherit; font-size: 14px; cursor: pointer; }
.group-panel-tabs button[aria-selected="true"] { color: #08776f; font-weight: 600; }
.group-panel-tabs button[aria-selected="true"]::after { content: ''; position: absolute; bottom: -1px; left: 0; right: 0; height: 2px; background: #08776f; }
.group-panel-content { padding: 20px; min-height: 0; overflow-y: auto; }
.group-name-row { display: flex; align-items: center; justify-content: space-between; font-size: 13px; color: #7a8b86; }
.group-edit-name { display: inline-flex; align-items: center; gap: 4px; padding: 2px 0; border: 0; color: #168178; background: transparent; font: inherit; font-size: 13px; cursor: pointer; }
.group-current-name { margin: 10px 0 20px; color: #25484a; font-size: 14px; font-weight: 500; line-height: 1.7; overflow-wrap: anywhere; }
.group-management-actions { display: grid; gap: 4px; margin-bottom: 20px; }
.group-management-actions button { display: flex; align-items: center; gap: 10px; width: 100%; padding: 12px 0; background: transparent; border: 0; color: #42736e; font: inherit; font-size: 14px; cursor: pointer; text-align: left; }
.group-management-actions button span { flex: 1; }
.group-management-actions button:hover { color: #08776f; }
.group-members-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding-top: 20px; border-top: 1px solid #edf1ef; }
.group-members-heading h3 { margin: 0; font-size: 14px; font-weight: 600; }
.group-members-heading h3 span { margin-left: 6px; color: #7a8b86; font-size: 12px; font-weight: 400; }
.group-sync-label { color: #168178; font-size: 12px; }
.group-sidebar-actions { display: flex; align-items: center; gap: 6px; }
.group-settings-button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 6px 9px; border: 1px solid #dce7e3; border-radius: 6px; background: white; color: #42736e; font: inherit; font-size: 13px; cursor: pointer; white-space: nowrap; }
.group-settings-button:hover, .group-small-button:hover { background: #f3f8f6; border-color: #b9d4cd; }
.group-sidebar-members { margin-top: 12px; }
.group-person { display: flex; align-items: center; gap: 10px; padding: 12px 0; }
.group-person-avatar { display: flex; flex: 0 0 36px; height: 36px; align-items: center; justify-content: center; border-radius: 9px; background: #edf5f2; color: #347b70; font-size: 14px; }
.group-person > div { min-width: 0; flex: 1; }
.group-person strong { font-size: 14px; overflow-wrap: anywhere; font-weight: 600; }
.group-person strong small { margin-left: 7px; color: #7a8c87; font-size: 12px; font-weight: 400; }
.group-person p { margin: 3px 0 0; color: #7a8b86; font-size: 12px; }
.group-owner { color: #168178; font-size: 12px; white-space: nowrap; }
.group-editor { display: flex; flex-direction: column; box-sizing: border-box; width: min(480px, calc(100vw - 32px)); max-height: calc(100dvh - 48px); border: 1px solid #e4ebe8; border-radius: 12px; background: white; color: #193b3d; font-size: 14px; box-shadow: 0 18px 60px #183b3b26; overflow: hidden; }
.group-editor-members { width: min(850px, calc(100vw - 32px)); overflow: visible; }
.group-editor-wide { width: min(640px, calc(100vw - 32px)); }
.group-editor-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 18px 24px; border-bottom: 1px solid #edf1ef; }
.group-editor h2 { margin: 0; font-size: 18px; font-weight: 600; }
.group-close { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; padding: 0; border: 0; border-radius: 5px; background: transparent; color: #748782; cursor: pointer; }
.group-close:hover { background: #f0f5f3; color: #08776f; }
.group-editor-body { padding: 24px; min-height: 0; overflow-y: auto; }
.group-settings-form { min-height: 0; overflow: auto; }
.group-field-label { display: block; margin-bottom: 10px; font-size: 14px; }
.group-settings-form input { box-sizing: border-box; width: 100%; min-width: 0; min-height: 40px; border: 1px solid #cbded7; border-radius: 6px; padding: 9px 12px; color: inherit; background: white; font: inherit; font-size: 14px; }
.group-editor footer { display: flex; flex: 0 0 auto; align-items: center; justify-content: flex-end; gap: 10px; padding: 16px 24px; border-top: 1px solid #edf1ef; }
.group-small-button, .group-primary-button { padding: 7px 16px; min-height: 34px; border: 1px solid #d5e2dd; border-radius: 6px; background: white; color: #42736e; font: inherit; font-size: 14px; cursor: pointer; }
.group-primary-button { background: #08776f; color: white; border-color: #08776f; }
.group-primary-button:hover:not(:disabled) { background: #09665f; }
button:disabled { opacity: .5; cursor: default; }
button:focus-visible, input:focus-visible, select:focus-visible { outline: 2px solid #13968c; outline-offset: 2px; }
.group-selection-count { margin-right: auto; color: #7a8b86; font-size: 13px; }
.group-owner-select { display: grid; gap: 10px; }
.group-owner-body { overflow: visible; }
.group-editor:has(.group-owner-body) { overflow: visible; }
.group-transfer-note { margin: 14px 0 0; font-size: 13px; color: #6b827b; line-height: 1.6; }
.group-file-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding-bottom: 16px; margin-bottom: 8px; border-bottom: 1px solid #edf1ef; }
.group-file-heading { display: flex; align-items: center; gap: 7px; min-width: 0; color: #52776f; }
.group-file-heading strong { font-size: 14px; font-weight: 600; color: #264b48; white-space: nowrap; }
.group-file-count { min-width: 20px; padding: 1px 5px; box-sizing: border-box; border-radius: 4px; background: #f0f5f3; color: #728b83; font-size: 12px; text-align: center; font-variant-numeric: tabular-nums; }
.group-members-note { margin: 0 0 12px; padding: 12px; border-radius: 6px; background: #f4f8f6; color: #72877f; font-size: 13px; line-height: 1.7; }
.group-remove-button { padding: 2px 0; border: 0; background: transparent; color: #af6655; font: inherit; font-size: 13px; cursor: pointer; }
.group-sync-label { margin: 10px 0 0; line-height: 1.6; }
.group-file { width: 100%; display: flex; align-items: center; gap: 12px; padding: 16px 0; border: 0; border-bottom: 1px solid #e5eeeb; text-align: left; background: transparent; color: inherit; cursor: pointer; font: inherit; }
.group-file > .n-icon { color: #508a7e; flex-shrink: 0; }
.group-file > span { min-width: 0; flex: 1; }
.group-file strong { font-size: 14px; font-weight: 500; overflow-wrap: anywhere; }
.group-file small { display: flex; justify-content: space-between; gap: 8px; margin-top: 5px; color: #7a8b86; font-size: 12px; }
.group-empty { padding: 32px 0; color: #768a84; font-size: 14px; line-height: 1.6; text-align: center; }
.group-empty > .n-icon { color: #a4c1b7; }
.group-more { display: block; margin: 18px auto 0; }
</style>
<style scoped src="./ChatTitleField.css"></style>

<style scoped>
.group-members-footer { border-radius: 0 0 12px 12px; }
.group-owner-note { margin: 10px 0 0; color: #718780; font-size: 12px; }
.group-sync-choice { display: inline-flex; align-items: center; gap: 7px; color: #365b54; font-size: 12px; white-space: nowrap; }
.group-sync-choice input { width: 14px; height: 14px; accent-color: #08776f; }
.group-all-badge { padding: 2px 5px; border: 1px solid #b5d7ca; border-radius: 3px; color: #257d66; background: white; font-size: 12px; }
.group-member-muted { color: #9baba6; }
.group-person { min-height: 42px; }
</style>
