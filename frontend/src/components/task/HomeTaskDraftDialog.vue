<template>
  <button
    v-if="activeDraft && !dialogOpen"
    type="button"
    class="home-task-draft-launcher"
    @click="openDialog"
  >
    <span><n-icon :size="17"><ClipboardCheck /></n-icon></span>
    <span>
      <strong>{{ launcherTitle }}</strong>
      <small>{{ launcherDescription }}</small>
    </span>
    <ChevronRight :size="17" />
  </button>

  <n-modal
    v-model:show="dialogOpen"
    :auto-focus="true"
    :close-on-esc="!isPublishing"
    :mask-closable="false"
  >
    <section class="home-task-dialog" role="dialog" aria-modal="true" aria-labelledby="home-task-dialog-title">
      <header class="home-task-dialog-head">
        <span class="home-task-dialog-icon"><n-icon :size="22"><ClipboardCheck /></n-icon></span>
        <div>
          <h2 id="home-task-dialog-title">布置任务</h2>
          <p>{{ requestSummary }}</p>
        </div>
        <b :class="['home-task-status', `is-${statusName}`]">{{ statusLabel }}</b>
        <button type="button" aria-label="关闭" :disabled="isPublishing" @click="closeDialog">
          <X :size="20" />
        </button>
      </header>

      <div v-if="isGenerating" class="home-task-progress" role="status" aria-live="polite">
        <div class="home-task-progress-visual" aria-hidden="true">
          <span><n-icon :size="30"><Robot /></n-icon></span>
          <i></i><i></i><i></i>
        </div>
        <h3>任务助手正在分析任务需求</h3>
        <p>正在结合当前对话梳理目标、时间、责任人与交付要求。</p>
        <ol>
          <li class="active"><b>1</b><span>读取对话上下文</span></li>
          <li class="active"><b>2</b><span>提取任务要素</span></li>
          <li class="active"><b>3</b><span>整理可编辑草稿</span></li>
        </ol>
      </div>

      <div v-else-if="isPublishing" class="home-task-progress is-publishing" role="status" aria-live="polite">
        <div class="home-task-progress-visual" aria-hidden="true">
          <span><n-icon :size="30"><ClipboardCheck /></n-icon></span>
          <i></i><i></i><i></i>
        </div>
        <h3>正在发布任务</h3>
        <p>正在写入任务中心并同步正式任务消息，请勿重复操作。</p>
      </div>

      <div v-else-if="isUnavailable" class="home-task-unavailable" role="alert">
        <span><n-icon :size="30"><AlertCircle /></n-icon></span>
        <h3>{{ statusName === 'cancelled' ? '任务助手已停止分析' : '任务助手未能完成分析' }}</h3>
        <p>{{ startError || activeDraft?.error || '分析过程遇到问题，请重新尝试。' }}</p>
        <small>当前内容没有发布，也没有创建任务。</small>
      </div>

      <form v-else-if="form" class="home-task-form" @submit.prevent="publishDraft">
        <section class="home-task-form-section">
          <div class="home-task-section-title">
            <span>01</span>
            <div><h3>任务内容</h3><p>{{ actionTypeLabel }}</p></div>
          </div>
          <label class="home-task-field full">
            <span>任务名称</span>
            <input v-model.trim="form.title" type="text" maxlength="120" required>
          </label>
          <label class="home-task-field full">
            <span>分析依据</span>
            <textarea v-model.trim="form.trigger_reason" rows="2" maxlength="1000"></textarea>
          </label>
        </section>

        <section class="home-task-form-section">
          <div class="home-task-section-title">
            <span>02</span>
            <div><h3>执行时间</h3><p>确认何时触发这项工作</p></div>
          </div>
          <div class="home-task-grid three">
            <label class="home-task-field">
              <span>执行方式</span>
              <select v-model="form.run_mode">
                <option value="immediate">立即执行</option>
                <option value="once">单次定时</option>
                <option value="recurring">周期执行</option>
              </select>
            </label>
            <label v-if="form.run_mode !== 'immediate'" class="home-task-field">
              <span>首次日期</span>
              <input v-model="form.trigger_date" type="date" required>
            </label>
            <label v-if="form.run_mode !== 'immediate'" class="home-task-field">
              <span>执行时间</span>
              <input v-model="form.trigger_time" type="time" required>
            </label>
          </div>
          <div v-if="form.run_mode === 'recurring'" class="home-task-grid two compact">
            <label class="home-task-field">
              <span>执行间隔</span>
              <input v-model.number="form.trigger_interval_value" type="number" min="1" max="999" required>
            </label>
            <label class="home-task-field">
              <span>间隔单位</span>
              <select v-model="form.trigger_interval_unit">
                <option value="minute">分钟</option>
                <option value="hour">小时</option>
                <option value="day">天</option>
                <option value="week">周</option>
                <option value="month">月</option>
              </select>
            </label>
          </div>
        </section>

        <section v-if="form.action_type === 'project_chat_message'" class="home-task-form-section">
          <div class="home-task-section-title">
            <span>03</span>
            <div><h3>群聊发布</h3><p>确认目标群聊、提醒范围和消息内容</p></div>
          </div>
          <div class="home-task-grid two">
            <label class="home-task-field">
              <span>目标群聊</span>
              <select v-model="form.target_channel_id" required>
                <option v-for="channel in channels" :key="channel.id" :value="channel.id">{{ channelTitle(channel) }}</option>
              </select>
            </label>
            <label class="home-task-field">
              <span>提醒范围</span>
              <select v-model="form.mention_mode">
                <option value="none">不艾特成员</option>
                <option value="all">全体成员</option>
                <option value="users">指定成员</option>
              </select>
            </label>
          </div>
          <div v-if="form.mention_mode === 'users'" class="home-task-recipients">
            <label class="home-task-field">
              <span>添加成员</span>
              <select v-model="memberToAdd" @change="addMember">
                <option value="">选择要提醒的成员</option>
                <option v-for="person in availablePeople" :key="person.user_id" :value="String(person.user_id)">{{ person.name }} · {{ person.title }}</option>
              </select>
            </label>
            <div class="home-task-recipient-cards" aria-label="已选择提醒成员">
              <span v-for="person in selectedPeople" :key="person.user_id">
                <b>{{ person.name }}</b>
                <button type="button" :aria-label="`移除${person.name}`" @click="removeMember(person.user_id)"><X :size="14" /></button>
              </span>
              <em v-if="!selectedPeople.length">还没有选择提醒成员</em>
            </div>
          </div>
          <label class="home-task-field full">
            <span>消息正文</span>
            <textarea v-model.trim="form.message_content" rows="4" maxlength="8000" required></textarea>
          </label>
        </section>

        <section v-else class="home-task-form-section">
          <div class="home-task-section-title">
            <span>03</span>
            <div><h3>责任配置</h3><p>任务发布后进入任务中心持续跟踪</p></div>
          </div>
          <div class="home-task-grid two">
            <label class="home-task-field">
              <span>默认责任人</span>
              <select v-model="form.assignee_user_id">
                <option :value="null">请选择</option>
                <option v-for="person in people" :key="person.user_id" :value="person.user_id">{{ person.name }}</option>
              </select>
            </label>
            <label class="home-task-field">
              <span>确认人</span>
              <select v-model="form.confirmer_user_id">
                <option :value="null">请选择</option>
                <option v-for="person in people" :key="person.user_id" :value="person.user_id">{{ person.name }}</option>
              </select>
            </label>
            <label class="home-task-field">
              <span>关联 WBS</span>
              <select v-model="form.wbs_item_id">
                <option :value="null">不关联</option>
                <option v-for="item in store.wbsItems" :key="item.id" :value="Number(item.id)">{{ item.name }}</option>
              </select>
            </label>
            <label class="home-task-field">
              <span>关联风险源</span>
              <select v-model="form.risk_source_id">
                <option :value="null">不关联</option>
                <option v-for="risk in store.riskSources" :key="risk.id" :value="Number(risk.id)">{{ risk.name }}</option>
              </select>
            </label>
          </div>
          <div class="home-task-steps">
            <article v-for="(step, index) in form.workflow_steps" :key="index">
              <b>{{ index + 1 }}</b>
              <label class="home-task-field">
                <span>节点名称</span>
                <input v-model.trim="step.name" type="text" maxlength="80" required>
              </label>
              <label v-if="step.node_type === 'manual'" class="home-task-field">
                <span>责任人</span>
                <select v-model="step.owner_user_id" required>
                  <option :value="null">请选择</option>
                  <option v-for="person in people" :key="person.user_id" :value="person.user_id">{{ person.name }}</option>
                </select>
              </label>
              <label v-if="step.node_type === 'manual'" class="home-task-field full">
                <span>交付材料</span>
                <input v-model.trim="step.material" type="text" maxlength="200">
              </label>
            </article>
          </div>
        </section>

        <p v-if="formError" class="home-task-error" role="alert">{{ formError }}</p>
      </form>

      <footer class="home-task-dialog-footer">
        <span>{{ footerHint }}</span>
        <div v-if="isGenerating">
          <button type="button" class="secondary" :disabled="actionBusy" :aria-busy="dismissing" @click="dismissDraft"><n-icon v-if="dismissing" :size="16" class="home-task-spinner"><Loader /></n-icon>{{ dismissing ? '正在取消…' : '取消本次' }}</button>
          <button type="button" @click="closeDialog">后台继续</button>
        </div>
        <div v-else-if="isPublishing"><button type="button" disabled>正在发布…</button></div>
        <div v-else-if="isUnavailable">
          <button type="button" class="secondary" :disabled="actionBusy" :aria-busy="dismissing" @click="dismissDraft"><n-icon v-if="dismissing" :size="16" class="home-task-spinner"><Loader /></n-icon>{{ dismissing ? '正在关闭…' : '关闭本次' }}</button>
          <button v-if="activeDraft" type="button" :disabled="actionBusy" @click="retryDraft">
            <n-icon v-if="retrying" :size="16" class="home-task-spinner"><Loader /></n-icon>
            {{ retrying ? '重新分析中…' : '重新分析' }}
          </button>
        </div>
        <div v-else>
          <button type="button" class="secondary" :disabled="actionBusy" :aria-busy="dismissing" @click="dismissDraft"><n-icon v-if="dismissing" :size="16" class="home-task-spinner"><Loader /></n-icon>{{ dismissing ? '正在取消…' : '取消本次' }}</button>
          <button type="button" :disabled="!canPublish" @click="publishDraft">
            <n-icon v-if="publishing" :size="16" class="home-task-spinner"><Loader /></n-icon>
            {{ publishing ? '发布中…' : '确认发布任务' }}
          </button>
        </div>
      </footer>
    </section>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { NIcon, NModal, useMessage } from 'naive-ui'
import { AlertCircle, ChevronRight, ClipboardCheck, Loader, Robot, X } from '@vicons/tabler'

import {
  createHomeAgentTaskDraft,
  dismissPrivateProjectChatTaskDraft,
  getProjectChatTaskDraft,
  listProjectChatChannels,
  listProjectChatParticipants,
  listProjectChatTaskDrafts,
  publishPrivateProjectChatTaskDraft,
  retryPrivateProjectChatTaskDraft,
  stopPrivateProjectChatTaskDraft,
  type ProjectChatChannel,
  type ProjectChatParticipant,
  type ProjectChatPrivateTaskDraft,
  type ProjectChatTaskDraft,
} from '@/api/projectChat'
import { useAppStore } from '@/stores/app'

const props = defineProps<{ projectId: string }>()
const emit = defineEmits<{ published: [] }>()
const store = useAppStore()
const notice = useMessage()

const dialogOpen = ref(false)
const activeDraft = ref<ProjectChatPrivateTaskDraft | null>(null)
const form = ref<ProjectChatTaskDraft | null>(null)
const channels = ref<ProjectChatChannel[]>([])
const people = ref<ProjectChatParticipant[]>([])
const memberToAdd = ref('')
const requestPreview = ref('')
const startError = ref('')
const formError = ref('')
const creating = ref(false)
const publishing = ref(false)
const dismissing = ref(false)
const retrying = ref(false)
const cancelPendingCreation = ref(false)
let pollTimer: number | null = null
let loadRevision = 0

const actionBusy = computed(() => publishing.value || dismissing.value || retrying.value)
const statusName = computed(() => {
  if (publishing.value) return 'publishing'
  if (creating.value) return 'generating'
  if (startError.value) return 'failed'
  return activeDraft.value?.status || 'generating'
})
const statusLabel = computed(() => ({
  generating: '任务助手分析中',
  ready: '待你确认',
  publishing: '正在发布',
  published: '已经发布',
  dismissed: '已经关闭',
  cancelled: '已停止',
  failed: '分析失败',
}[statusName.value] || '处理中'))
const isGenerating = computed(() => creating.value || activeDraft.value?.status === 'generating')
const isPublishing = computed(() => publishing.value || activeDraft.value?.status === 'publishing')
const isUnavailable = computed(() => Boolean(
  startError.value || ['failed', 'cancelled'].includes(activeDraft.value?.status || ''),
))
const requestSummary = computed(() => {
  const text = (activeDraft.value?.request_text || requestPreview.value || '正在读取当前对话').replace(/\s+/g, ' ').trim()
  return text.length > 110 ? `${text.slice(0, 110)}…` : text
})
const actionTypeLabel = computed(() => (
  form.value?.action_type === 'project_chat_message'
    ? '定时发送项目群消息'
    : '创建责任任务并跟踪闭环'
))
const selectedPeople = computed(() => {
  const selected = new Set(form.value?.mentioned_user_ids || [])
  return people.value.filter(person => selected.has(person.user_id))
})
const availablePeople = computed(() => {
  const selected = new Set(form.value?.mentioned_user_ids || [])
  return people.value.filter(person => !selected.has(person.user_id))
})
const canPublish = computed(() => {
  const value = form.value
  if (!value || activeDraft.value?.status !== 'ready' || actionBusy.value) return false
  if (!value.title.trim()) return false
  if (value.run_mode !== 'immediate' && (!value.trigger_date || !value.trigger_time)) return false
  if (value.run_mode === 'recurring' && value.trigger_interval_value < 1) return false
  if (value.action_type === 'project_chat_message') {
    return Boolean(
      value.target_channel_id
      && value.message_content?.trim()
      && (value.mention_mode !== 'users' || value.mentioned_user_ids.length),
    )
  }
  return Boolean(
    value.confirmer_user_id
    && value.wbs_item_id
    && value.workflow_steps.length
    && value.workflow_steps.every(step => (
      step.node_type !== 'manual' || step.owner_user_id || value.assignee_user_id
    )),
  )
})
const launcherTitle = computed(() => ({
  generating: '任务助手正在分析任务',
  ready: '任务草稿等待确认',
  publishing: '任务正在发布',
  failed: '任务分析失败',
  cancelled: '任务分析已停止',
} as Record<string, string>)[activeDraft.value?.status || ''] || '继续处理任务草稿')
const launcherDescription = computed(() => (
  activeDraft.value?.status === 'ready'
    ? activeDraft.value.draft?.title || '打开并确认发布'
    : requestSummary.value
))
const footerHint = computed(() => {
  if (isGenerating.value) return '草稿只对你可见，关闭弹框后仍可继续等待'
  if (isPublishing.value) return '发布完成后，群内才会出现正式任务消息'
  if (isUnavailable.value) return '你可以重新分析，或关闭并放弃本次草稿'
  return '发布前可修改；确认后才会写入任务中心'
})

function errorDetail(error: any, fallback: string) {
  return error?.response?.data?.detail || error?.message || fallback
}

function channelTitle(channel: ProjectChatChannel) {
  return channel.channel_type === 'project'
    ? store.currentProject?.name || channel.title.replace(/项目群$/, '')
    : channel.title
}

function cloneDraft(value: ProjectChatTaskDraft): ProjectChatTaskDraft {
  return {
    ...value,
    required_materials: [...(value.required_materials || [])],
    mentioned_user_ids: [...(value.mentioned_user_ids || [])],
    workflow_steps: (value.workflow_steps || []).map(step => ({
      ...step,
      action: step.action ? {
        ...step.action,
        mentioned_user_ids: [...(step.action.mentioned_user_ids || [])],
      } : undefined,
    })),
    target_channel_id: value.target_channel_id
      || channels.value.find(channel => channel.channel_type === 'project')?.id
      || null,
  }
}

function clearPoll() {
  if (pollTimer !== null) window.clearTimeout(pollTimer)
  pollTimer = null
}

function resetDraft() {
  clearPoll()
  activeDraft.value = null
  form.value = null
  memberToAdd.value = ''
  requestPreview.value = ''
  startError.value = ''
  formError.value = ''
}

function applyDraft(row: ProjectChatPrivateTaskDraft, open = false) {
  const previousStatus = activeDraft.value?.status
  if (row.status === 'published' || row.status === 'dismissed') {
    resetDraft()
    dialogOpen.value = false
    return
  }
  activeDraft.value = row
  requestPreview.value = row.request_text
  startError.value = ''
  if (row.status === 'ready' && row.draft) {
    if (!form.value || previousStatus !== 'ready') form.value = cloneDraft(row.draft)
    if (previousStatus === 'generating') notice.success('Dobby 已整理好任务草稿，请确认后发布。')
  } else {
    form.value = null
  }
  if (open) dialogOpen.value = true
  if (row.status === 'generating' || row.status === 'publishing') schedulePoll(row.id)
  else clearPoll()
}

function schedulePoll(draftId: number) {
  clearPoll()
  pollTimer = window.setTimeout(async () => {
    try {
      const row = await getProjectChatTaskDraft(draftId)
      if (activeDraft.value?.id === draftId) applyDraft(row)
    } catch {
      // A transient polling error should not discard the user's private draft.
      if (activeDraft.value?.id === draftId) schedulePoll(draftId)
    }
  }, 1200)
}

async function loadSupportData(projectId: string) {
  if (!projectId) return
  const [channelRows, participantRows] = await Promise.all([
    listProjectChatChannels(projectId),
    listProjectChatParticipants(projectId),
  ])
  if (props.projectId !== projectId) return
  channels.value = channelRows
  people.value = participantRows
}

async function loadActiveDraft(projectId: string) {
  const revision = ++loadRevision
  resetDraft()
  dialogOpen.value = false
  channels.value = []
  people.value = []
  if (!projectId) return
  try {
    const rows = await listProjectChatTaskDrafts(projectId)
    if (revision === loadRevision && rows[0]) {
      await loadSupportData(projectId)
      if (revision === loadRevision) applyDraft(rows[0])
    }
  } catch {
    // The homepage itself remains usable when the optional task draft lookup fails.
  }
}

async function start(conversationId: number | null, requirement: string) {
  const projectId = props.projectId
  const cleanRequirement = requirement.replace('@任务助手', '').trim()
  if (cleanRequirement.length < 4) {
    notice.warning('请在 @任务助手 后说明要布置的任务。')
    return false
  }
  if (activeDraft.value) {
    openDialog()
    notice.warning('请先处理当前任务草稿。')
    return false
  }
  requestPreview.value = cleanRequirement
  startError.value = ''
  formError.value = ''
  creating.value = true
  cancelPendingCreation.value = false
  dialogOpen.value = true
  try {
    const row = await createHomeAgentTaskDraft(projectId, conversationId, requirement)
    if (props.projectId !== projectId) {
      resetDraft()
      dialogOpen.value = false
      return false
    }
    await loadSupportData(projectId)
    if (cancelPendingCreation.value) {
      if (row.status === 'generating') await stopPrivateProjectChatTaskDraft(row.id)
      await dismissPrivateProjectChatTaskDraft(row.id)
      resetDraft()
      dialogOpen.value = false
      return false
    }
    applyDraft(row, true)
    return true
  } catch (error: any) {
    if (error?.response?.status === 409 && projectId && props.projectId === projectId) {
      try {
        const rows = await listProjectChatTaskDrafts(projectId)
        if (rows[0]) {
          applyDraft(rows[0], true)
          notice.warning('已为你打开尚未处理的任务草稿。')
          return false
        }
      } catch {
        // Fall through to the original request error.
      }
    }
    startError.value = errorDetail(error, '无法启动 Dobby 任务分析。')
    return false
  } finally {
    creating.value = false
    cancelPendingCreation.value = false
  }
}

async function openExisting(draftId: number) {
  if (!draftId || actionBusy.value) return false
  try {
    const row = await getProjectChatTaskDraft(draftId)
    if (String(row.project_id) !== props.projectId) return false
    await loadSupportData(props.projectId)
    applyDraft(row, true)
    return true
  } catch (error: any) {
    notice.error(errorDetail(error, '无法打开 Dobby 生成的任务草稿。'))
    return false
  }
}

function openDialog() {
  formError.value = ''
  dialogOpen.value = true
  if (activeDraft.value?.status === 'ready' && activeDraft.value.draft && !form.value) {
    form.value = cloneDraft(activeDraft.value.draft)
  }
}

function closeDialog() {
  if (isPublishing.value || dismissing.value) return
  dialogOpen.value = false
}

function addMember() {
  const userId = Number(memberToAdd.value)
  if (!form.value || !userId) return
  form.value.mentioned_user_ids = [...new Set([...form.value.mentioned_user_ids, userId])]
  memberToAdd.value = ''
}

function removeMember(userId: number) {
  if (!form.value) return
  form.value.mentioned_user_ids = form.value.mentioned_user_ids.filter(id => id !== userId)
}

async function retryDraft() {
  if (!activeDraft.value || actionBusy.value) return
  retrying.value = true
  formError.value = ''
  try {
    applyDraft(await retryPrivateProjectChatTaskDraft(activeDraft.value.id), true)
  } catch (error: any) {
    formError.value = errorDetail(error, 'Dobby 重新分析任务失败。')
  } finally {
    retrying.value = false
  }
}

async function dismissDraft() {
  if (actionBusy.value) return
  if (!activeDraft.value) {
    cancelPendingCreation.value = creating.value
    dialogOpen.value = false
    startError.value = ''
    return
  }
  dismissing.value = true
  formError.value = ''
  try {
    if (activeDraft.value.status === 'generating') {
      await stopPrivateProjectChatTaskDraft(activeDraft.value.id)
    }
    await dismissPrivateProjectChatTaskDraft(activeDraft.value.id)
    resetDraft()
    dialogOpen.value = false
  } catch (error: any) {
    formError.value = errorDetail(error, '取消任务草稿失败。')
  } finally {
    dismissing.value = false
  }
}

async function publishDraft() {
  if (!activeDraft.value || !form.value || !canPublish.value) return
  publishing.value = true
  formError.value = ''
  try {
    const payload: ProjectChatTaskDraft = {
      ...form.value,
      title: form.value.title.trim(),
      trigger_reason: form.value.trigger_reason?.trim() || null,
      message_content: form.value.message_content?.trim() || null,
      workflow_steps: form.value.workflow_steps.map(step => ({
        ...step,
        owner_user_id: step.node_type === 'manual'
          ? step.owner_user_id || form.value?.assignee_user_id || null
          : null,
        material: step.material?.trim() || '',
      })),
    }
    const response = await publishPrivateProjectChatTaskDraft(activeDraft.value.id, payload)
    notice.success(response.message || '任务已发布。')
    resetDraft()
    dialogOpen.value = false
    await store.loadProjectData()
    emit('published')
  } catch (error: any) {
    formError.value = errorDetail(error, '发布任务失败。')
  } finally {
    publishing.value = false
  }
}

watch(() => props.projectId, projectId => void loadActiveDraft(projectId), { immediate: true })
onBeforeUnmount(() => clearPoll())

defineExpose({ openExisting, start })
</script>

<style scoped>
.home-task-draft-launcher {
  position: fixed;
  z-index: 80;
  right: 28px;
  bottom: 28px;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  width: min(360px, calc(100vw - 32px));
  padding: 10px 12px;
  border: 1px solid rgba(15, 118, 110, 0.24);
  border-radius: 12px;
  color: #173a3d;
  text-align: left;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 16px 40px rgba(17, 61, 62, 0.18);
  cursor: pointer;
  backdrop-filter: blur(12px);
}

.home-task-draft-launcher > span:first-child {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border-radius: 9px;
  color: #fff;
  background: #0f766e;
}

.home-task-draft-launcher > span:nth-child(2) { display: grid; min-width: 0; gap: 2px; }
.home-task-draft-launcher strong,
.home-task-draft-launcher small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.home-task-draft-launcher strong { font-size: 13px; }
.home-task-draft-launcher small { color: #71858a; font-size: 12px; }

.home-task-dialog {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  width: min(940px, calc(100vw - 32px));
  max-height: min(820px, calc(100vh - 32px));
  overflow: hidden;
  border: 1px solid rgba(20, 64, 67, 0.14);
  border-radius: 16px;
  color: #17383d;
  background: #f7faf9;
  box-shadow: 0 28px 80px rgba(13, 45, 49, 0.24);
}

.home-task-dialog-head {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) auto 36px;
  align-items: center;
  gap: 12px;
  padding: 16px 18px;
  border-bottom: 1px solid rgba(20, 64, 67, 0.1);
  background: #fff;
}

.home-task-dialog-icon {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border-radius: 11px;
  color: #0f766e;
  background: #e7f4f1;
}

.home-task-dialog-head h2 { margin: 0; font-size: 18px; line-height: 1.25; }
.home-task-dialog-head p { overflow: hidden; margin: 4px 0 0; color: #71858a; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.home-task-dialog-head > button { display: grid; width: 36px; height: 36px; place-items: center; border: 0; border-radius: 8px; color: #6f8186; background: transparent; cursor: pointer; }
.home-task-dialog-head > button:hover:not(:disabled) { color: #17383d; background: #edf3f1; }

.home-task-status { padding: 5px 9px; border-radius: 999px; color: #0f766e; font-size: 12px; background: #e3f3ef; }
.home-task-status.is-failed,
.home-task-status.is-cancelled { color: #b54708; background: #fff0e4; }
.home-task-status.is-publishing { color: #175cd3; background: #eaf2ff; }

.home-task-progress,
.home-task-unavailable {
  display: grid;
  min-height: 430px;
  place-content: center;
  justify-items: center;
  padding: 36px;
  text-align: center;
}

.home-task-progress-visual { position: relative; display: grid; width: 104px; height: 82px; place-items: center; }
.home-task-progress-visual span { z-index: 2; display: grid; width: 58px; height: 58px; place-items: center; border-radius: 18px; color: #0f766e; background: #e4f3f0; box-shadow: 0 12px 28px rgba(15, 118, 110, 0.18); }
.home-task-progress-visual i { position: absolute; width: 10px; height: 10px; border-radius: 50%; background: #7cc5bc; animation: home-task-orbit 1.8s linear infinite; }
.home-task-progress-visual i:nth-child(2) { animation-delay: -0.6s; }
.home-task-progress-visual i:nth-child(3) { animation-delay: -1.2s; }
.home-task-progress h3,
.home-task-unavailable h3 { margin: 16px 0 7px; font-size: 17px; }
.home-task-progress > p,
.home-task-unavailable p { max-width: 520px; margin: 0; color: #6f8287; font-size: 13px; line-height: 1.65; }
.home-task-progress ol { display: flex; gap: 22px; margin: 28px 0 0; padding: 0; list-style: none; }
.home-task-progress li { display: flex; align-items: center; gap: 7px; color: #61767b; font-size: 12px; }
.home-task-progress li b { display: grid; width: 22px; height: 22px; place-items: center; border-radius: 50%; color: #fff; font-size: 12px; background: #0f766e; }
.home-task-unavailable > span { display: grid; width: 58px; height: 58px; place-items: center; border-radius: 18px; color: #b54708; background: #fff0e4; }
.home-task-unavailable small { margin-top: 10px; color: #8a9699; font-size: 12px; }

.home-task-form { overflow-y: auto; padding: 16px 18px 20px; scrollbar-width: thin; }
.home-task-form-section { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; padding: 16px; border: 1px solid rgba(20, 64, 67, 0.11); border-radius: 12px; background: #fff; }
.home-task-section-title { grid-column: 1 / -1; display: flex; align-items: center; gap: 10px; margin-bottom: 1px; }
.home-task-section-title > span { display: grid; width: 31px; height: 31px; place-items: center; border-radius: 9px; color: #0f766e; font-size: 12px; font-weight: 800; background: #e6f3f0; }
.home-task-section-title h3 { margin: 0; font-size: 14px; }
.home-task-section-title p { margin: 2px 0 0; color: #7b8c90; font-size: 12px; }
.home-task-grid { grid-column: 1 / -1; display: grid; gap: 12px; }
.home-task-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.home-task-grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.home-task-grid.compact { max-width: 570px; }
.home-task-field { display: grid; min-width: 0; gap: 6px; }
.home-task-field.full { grid-column: 1 / -1; }
.home-task-field > span { color: #3c565b; font-size: 12px; font-weight: 700; }
.home-task-field input,
.home-task-field select,
.home-task-field textarea { width: 100%; min-width: 0; box-sizing: border-box; border: 1px solid #cfdcda; border-radius: 8px; outline: 0; color: #17383d; font: inherit; font-size: 13px; background: #fff; transition: border-color 0.15s ease, box-shadow 0.15s ease; }
.home-task-field input,
.home-task-field select { height: 38px; padding: 0 10px; }
.home-task-field textarea { min-height: 68px; padding: 9px 10px; line-height: 1.55; resize: vertical; }
.home-task-field input:focus,
.home-task-field select:focus,
.home-task-field textarea:focus { border-color: #0f766e; box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.09); }
.home-task-recipients { grid-column: 1 / -1; display: grid; grid-template-columns: minmax(220px, 0.42fr) minmax(0, 1fr); gap: 12px; }
.home-task-recipient-cards { display: flex; min-height: 38px; align-items: center; align-content: center; flex-wrap: wrap; gap: 7px; padding: 6px 8px; border: 1px solid #d9e3e1; border-radius: 8px; background: #f8fbfa; }
.home-task-recipient-cards > span { display: inline-flex; align-items: center; gap: 6px; padding: 5px 7px 5px 9px; border: 1px solid rgba(15, 118, 110, 0.16); border-radius: 7px; color: #155e59; background: #eaf5f2; }
.home-task-recipient-cards b { font-size: 12px; }
.home-task-recipient-cards button { display: grid; padding: 0; border: 0; color: #5e817e; background: transparent; cursor: pointer; }
.home-task-recipient-cards em { color: #8a999c; font-size: 12px; font-style: normal; }
.home-task-steps { grid-column: 1 / -1; display: grid; gap: 8px; }
.home-task-steps article { display: grid; grid-template-columns: 28px minmax(0, 1fr) minmax(0, 0.7fr); gap: 10px; padding: 11px; border: 1px solid #dce6e4; border-radius: 9px; background: #f8fbfa; }
.home-task-steps article > b { display: grid; width: 26px; height: 26px; place-items: center; margin-top: 22px; border-radius: 8px; color: #0f766e; font-size: 12px; background: #e5f3f0; }
.home-task-steps article .full { grid-column: 2 / -1; }
.home-task-error { grid-column: 1 / -1; margin: 0; padding: 9px 11px; border-radius: 8px; color: #b42318; font-size: 12px; background: #feeceb; }

.home-task-dialog-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; min-height: 66px; padding: 12px 18px; border-top: 1px solid rgba(20, 64, 67, 0.1); background: #fff; }
.home-task-dialog-footer > span { color: #71858a; font-size: 12px; }
.home-task-dialog-footer > div { display: flex; gap: 9px; }
.home-task-dialog-footer button { display: inline-flex; min-width: 108px; height: 38px; align-items: center; justify-content: center; gap: 7px; padding: 0 15px; border: 1px solid #0f766e; border-radius: 8px; color: #fff; font-size: 13px; font-weight: 750; background: #0f766e; cursor: pointer; }
.home-task-dialog-footer button.secondary { border-color: #cedbd9; color: #4c666b; background: #fff; }
.home-task-dialog-footer button:disabled { cursor: not-allowed; opacity: 0.5; }
.home-task-spinner { animation: home-task-spin 0.8s linear infinite; }

@keyframes home-task-orbit {
  from { transform: rotate(0deg) translateX(46px) rotate(0deg); }
  to { transform: rotate(360deg) translateX(46px) rotate(-360deg); }
}
@keyframes home-task-spin { to { transform: rotate(360deg); } }

@media (max-width: 720px) {
  .home-task-dialog { width: calc(100vw - 18px); max-height: calc(100vh - 18px); }
  .home-task-dialog-head { grid-template-columns: 38px minmax(0, 1fr) 34px; padding: 13px; }
  .home-task-status { display: none; }
  .home-task-form { padding: 12px; }
  .home-task-form-section { grid-template-columns: 1fr; padding: 13px; }
  .home-task-grid.two,
  .home-task-grid.three,
  .home-task-recipients { grid-template-columns: 1fr; }
  .home-task-steps article { grid-template-columns: 28px minmax(0, 1fr); }
  .home-task-steps article > .home-task-field { grid-column: 2; }
  .home-task-dialog-footer { align-items: stretch; flex-direction: column; }
  .home-task-dialog-footer > div { justify-content: flex-end; }
  .home-task-progress ol { align-items: flex-start; flex-direction: column; gap: 10px; }
}

@media (prefers-reduced-motion: reduce) {
  .home-task-progress-visual i,
  .home-task-spinner { animation: none; }
}
</style>
