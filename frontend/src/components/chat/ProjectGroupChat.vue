<template>
  <section class="project-chat-shell" aria-label="项目群聊">
    <aside class="channel-rail" aria-label="项目会话">
      <header class="rail-heading">
        <div class="heading-icon"><n-icon :size="19"><MessageCircle /></n-icon></div>
        <div class="rail-title">
          <h1>项目群聊</h1>
          <p>项目群与私密会话</p>
        </div>
        <button class="new-private-chat" type="button" title="发起私密会话" @click="openPrivateChatDialog">
          <n-icon :size="18"><Plus /></n-icon>
        </button>
      </header>

      <div class="channel-list">
        <div v-if="loadingChannels" class="channel-skeleton" aria-label="正在加载群聊">
          <i></i><span></span><small></small>
        </div>
        <template v-for="sectionItem in channelSections" :key="sectionItem.key">
          <div class="channel-section-label">
            <span>{{ sectionItem.label }}</span>
            <em>{{ sectionItem.channels.length }}</em>
          </div>
          <button
            v-for="channel in sectionItem.channels"
            :key="channel.id"
            type="button"
            :class="['channel-item', { active: channel.id === activeChannelId, private: channel.channel_type === 'private' }]"
            :aria-pressed="channel.id === activeChannelId"
            @click="activateChannel(channel.id)"
          >
            <span class="channel-symbol">
              <n-icon :size="17"><Lock v-if="channel.channel_type === 'private'" /><Hash v-else /></n-icon>
            </span>
            <span class="channel-copy">
              <strong>{{ channelDisplayTitle(channel) }}</strong>
              <small>{{ channel.last_message?.content || channel.summary || '还没有消息' }}</small>
            </span>
            <time v-if="channel.last_message_at">{{ compactTime(channel.last_message_at) }}</time>
          </button>
        </template>
        <div v-if="!loadingChannels && !channels.length && !pageError" class="rail-empty">
          当前项目还没有可用群聊
        </div>
      </div>

      <footer class="rail-foot">
        <n-icon :size="17"><Lock /></n-icon>
        <span>消息按项目隔离，非项目成员不可访问</span>
      </footer>
    </aside>

    <main class="chat-stage">
      <header class="chat-heading">
        <div class="chat-heading-main">
          <div class="chat-channel-mark">
            <n-icon :size="20"><Lock v-if="activeChannel?.channel_type === 'private'" /><Hash v-else /></n-icon>
          </div>
          <div>
            <h1>{{ displayChannelTitle }}</h1>
            <p><span class="current-project-name">{{ channelScopeLabel }}</span><span aria-hidden="true">·</span>{{ members.length }} 位成员共享</p>
          </div>
        </div>
        <div :class="['connection-state', realtimeStatus]" :title="connectionDescription">
          <n-icon :size="16"><Wifi v-if="realtimeStatus === 'connected'" /><WifiOff v-else /></n-icon>
          <span>{{ connectionLabel }}</span>
        </div>
      </header>

      <div v-if="pageError" class="chat-alert" role="alert">
        <n-icon :size="18"><AlertCircle /></n-icon>
        <span>{{ pageError }}</span>
        <button type="button" @click="reloadProjectChat">重试</button>
      </div>

      <div ref="messageViewport" class="message-viewport" aria-live="polite">
        <div v-if="loadingMessages" class="message-loading" aria-label="正在加载消息">
          <div v-for="index in 3" :key="index" :class="['message-placeholder', { own: index === 2 }]">
            <i></i><span></span>
          </div>
        </div>

        <div v-else-if="activeChannel && !messages.length" class="chat-empty">
          <div class="empty-robot"><n-icon :size="34"><Robot /></n-icon></div>
          <h3>{{ activeChannel.channel_type === 'private' ? '私密会话已经准备好' : '项目群已经准备好' }}</h3>
          <p>{{ activeChannel.channel_type === 'private' ? '只有当前参与人能够查看和发送消息。' : '发一条消息开始协作。普通群聊只在项目成员之间传递，不会自动调用智能体或创建任务。' }}</p>
        </div>

        <article
          v-for="item in messages"
          :key="item.id"
          :ref="element => registerMessageElement(item, element)"
          :data-message-id="item.id"
          :class="[
            'chat-message',
            {
              own: isOwnMessage(item),
              agent: item.sender_type === 'agent',
              mentioned: isMentioningCurrentUser(item),
              'mention-pulse': pulsingMentionIds.has(item.id),
              failed: Boolean(item.metadata?.failed),
            },
          ]"
        >
          <div class="sender-avatar" aria-hidden="true">
            <n-icon v-if="item.sender_type === 'agent'" :size="18"><Robot /></n-icon>
            <span v-else>{{ senderInitial(item) }}</span>
          </div>
          <div class="message-body">
            <div class="message-meta">
              <strong>{{ senderName(item) }}</strong>
              <span v-if="item.sender_type === 'agent'" class="agent-label">智能体</span>
              <span v-if="agentRuntimeLabel(item)" class="runtime-label">{{ agentRuntimeLabel(item) }}</span>
              <time>{{ messageTime(item.created_at) }}</time>
            </div>
            <div class="message-content">
              <template v-for="(segment, segmentIndex) in messageSegments(item)" :key="`${item.id}-${segmentIndex}`">
                <span
                  v-if="segment.targetType"
                  :class="['message-mention', segment.targetType]"
                >{{ segment.text }}</span>
                <template v-else>{{ segment.text }}</template>
              </template>
            </div>
            <div v-if="mentionedAgentNames(item).length" class="agent-request-note">
              <n-icon :size="15"><Robot /></n-icon>
              已通知 {{ mentionedAgentNames(item).join('、') }}，处理结果会自动回复到当前会话
            </div>
          </div>
        </article>
      </div>

      <footer class="message-composer">
        <div v-if="activeMentionNotice" class="mention-notice" role="status" aria-live="polite">
          <span class="mention-notice-icon" aria-hidden="true">
            <n-icon :size="17"><At /></n-icon>
          </span>
          <span class="mention-notice-copy">
            <strong>{{ activeMentionNoticeTitle }}</strong>
            <span>{{ activeMentionNoticeDescription }}</span>
          </span>
          <span v-if="mentionNotices.length > 1" class="mention-notice-count">
            {{ mentionNotices.length }} 条
          </span>
          <button
            type="button"
            class="mention-notice-locate"
            :disabled="locatingMentionNotice"
            @click="viewActiveMentionNotice"
          >
            {{ locatingMentionNotice ? '定位中' : '查看' }}
          </button>
        </div>
        <div v-if="realtimeStatus !== 'connected'" class="polling-note">
          实时通道暂未连接，页面会定时刷新；消息仍会正常保存。
          <button type="button" @click="manualRefresh">立即刷新</button>
        </div>
        <form @submit.prevent="sendMessage">
          <div v-if="mentionMenuOpen" class="mention-menu" role="listbox" aria-label="选择要提及的人员或智能体">
            <div v-if="filteredMentionOptions.length" class="mention-options">
              <button
                v-for="(option, optionIndex) in filteredMentionOptions"
                :key="option.key"
                type="button"
                role="option"
                :aria-selected="optionIndex === mentionActiveIndex"
                :class="['mention-option', option.type, { active: optionIndex === mentionActiveIndex }]"
                @mouseenter="mentionActiveIndex = optionIndex"
                @mousedown.prevent="selectMention(option)"
              >
                <span :class="['mention-avatar', option.type]">
                  <n-icon v-if="option.type === 'all'" :size="17"><At /></n-icon>
                  <n-icon v-else-if="option.type === 'agent'" :size="17"><Robot /></n-icon>
                  <n-icon v-else :size="17"><User /></n-icon>
                </span>
                <span class="mention-copy">
                  <strong>{{ option.name }}</strong>
                  <small>{{ option.subtitle }}</small>
                </span>
              </button>
            </div>
            <div v-else class="mention-empty">没有符合条件的可提及对象</div>
          </div>

          <div
            ref="composerInput"
            :contenteditable="Boolean(activeChannel && !sending)"
            :class="['composer-editor', { disabled: !activeChannel || sending }]"
            :data-empty="!draft"
            :data-placeholder="activeChannel ? `发消息到${displayChannelTitle}；输入 @ 提及成员或智能体` : '请先选择会话'"
            role="textbox"
            aria-multiline="true"
            aria-label="群聊消息"
            @blur="deferCloseMentionMenu"
            @click="updateMentionState"
            @input="updateMentionState"
            @paste="handleComposerPaste"
            @keydown="handleComposerKeydown"
          ></div>
          <div class="composer-actions">
            <div class="composer-tools">
              <button
                type="button"
                class="mention-trigger"
                :disabled="!activeChannel || sending"
                aria-label="提及成员或智能体"
                title="提及成员或智能体"
                @mousedown.prevent
                @click="openMentionMenu"
              >
                <n-icon :size="16"><At /></n-icon>
              </button>
              <div class="composer-hint">
                <span>Enter 发送 · Shift + Enter 换行</span>
                <span>普通消息不调用 AI，只有明确 @ 智能体才会参与</span>
              </div>
            </div>
            <button class="send-message" type="submit" :disabled="!canSend">
              <n-icon :size="17"><Send /></n-icon>
              {{ sending ? '发送中' : '发送' }}
            </button>
          </div>
        </form>
      </footer>
    </main>

    <aside class="chat-context" aria-label="群聊信息">
      <section class="context-section group-summary">
        <div class="context-eyebrow">{{ activeChannel?.channel_type === 'private' ? '私密会话' : '当前项目' }}</div>
        <h2>{{ activeChannel?.channel_type === 'private' ? displayChannelTitle : '项目协作群' }}</h2>
        <p>{{ activeChannel?.summary || '项目成员共享的实时协同群聊' }}</p>
        <dl>
          <div><dt>消息范围</dt><dd>{{ activeChannel?.channel_type === 'private' ? '仅参与人' : '当前项目' }}</dd></div>
          <div><dt>成员</dt><dd>{{ members.length }} 人</dd></div>
          <div><dt>消息记录</dt><dd>持续保存</dd></div>
        </dl>
      </section>

      <section class="context-section member-section">
        <header>
          <div>
            <span class="context-eyebrow">参与人</span>
            <h3>{{ activeChannel?.channel_type === 'private' ? '私聊成员' : '项目成员' }}</h3>
          </div>
          <span>{{ members.length }}</span>
        </header>
        <div class="member-list">
          <article v-for="member in members" :key="member.user_id" class="member-row">
            <div class="member-avatar">{{ member.name.slice(0, 1) }}</div>
            <div>
              <strong>{{ member.name }}<em v-if="member.user_id === currentUserId">我</em></strong>
              <small>{{ member.title }}</small>
            </div>
            <span v-if="member.member_role === 'owner'" class="owner-label">群主</span>
          </article>
        </div>
      </section>

      <section class="context-section agent-boundary">
        <div class="boundary-icon"><n-icon :size="20"><Robot /></n-icon></div>
        <div>
          <h3>智能体按需参与</h3>
          <p>输入 @ 可选择项目成员或已发布智能体。提及人员会定向提醒；只有明确提及智能体时，平台才传递当前项目与必要群聊上下文。</p>
        </div>
      </section>
    </aside>
  </section>

  <n-modal v-model:show="privateChatDialogOpen" :mask-closable="!creatingPrivateChat">
    <section class="private-chat-dialog" role="dialog" aria-modal="true" aria-labelledby="private-chat-dialog-title">
      <header>
        <div>
          <span>新建会话</span>
          <h2 id="private-chat-dialog-title">发起私密会话</h2>
          <p>只有你选择的当前项目成员可以看到会话和消息。</p>
        </div>
        <button type="button" aria-label="关闭" :disabled="creatingPrivateChat" @click="closePrivateChatDialog">
          <n-icon :size="20"><X /></n-icon>
        </button>
      </header>

      <div class="private-chat-form">
        <label class="private-chat-name">
          <span>会话名称 <em>选填</em></span>
          <input v-model="privateChatTitle" type="text" maxlength="100" placeholder="未填写时，将根据参与人自动命名">
        </label>

        <section class="participant-picker" aria-label="选择私密会话参与人">
          <div class="participant-picker-head">
            <div>
              <strong>选择参与人</strong>
              <span>已选 {{ selectedParticipantIds.length }} 人</span>
            </div>
            <label class="participant-search">
              <n-icon :size="17"><Search /></n-icon>
              <input v-model="participantSearch" type="search" placeholder="搜索姓名或岗位">
            </label>
          </div>

          <div v-if="loadingParticipants" class="participant-loading">正在加载项目成员…</div>
          <div v-else-if="filteredParticipants.length" class="participant-list">
            <label
              v-for="participant in filteredParticipants"
              :key="participant.user_id"
              :class="['participant-option', { selected: selectedParticipantIds.includes(participant.user_id) }]"
            >
              <input v-model="selectedParticipantIds" type="checkbox" :value="participant.user_id">
              <span class="participant-avatar">{{ participant.name.slice(0, 1) }}</span>
              <span class="participant-copy">
                <strong>{{ participant.name }}</strong>
                <small>{{ participant.title }}</small>
              </span>
              <span class="participant-check" aria-hidden="true">✓</span>
            </label>
          </div>
          <div v-else class="participant-empty">没有符合条件的项目成员</div>
        </section>

        <p v-if="privateChatError" class="private-chat-error" role="alert">{{ privateChatError }}</p>
      </div>

      <footer>
        <span>你会自动加入该会话并成为群主</span>
        <div>
          <button type="button" class="dialog-cancel" :disabled="creatingPrivateChat" @click="closePrivateChatDialog">取消</button>
          <button type="button" class="dialog-submit" :disabled="!canCreatePrivateChat" @click="createPrivateChat">
            {{ creatingPrivateChat ? '创建中…' : '创建会话' }}
          </button>
        </div>
      </footer>
    </section>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NIcon, NModal, useMessage } from 'naive-ui'
import dayjs from 'dayjs'
import {
  AlertCircle, At, Hash, Lock, MessageCircle, Plus, Robot, Search, Send, User, Wifi, WifiOff, X,
} from '@vicons/tabler'

import {
  claimProjectChatMention,
  connectProjectChatRealtime,
  createPrivateProjectChatChannel,
  getProjectChatMessage,
  listProjectChatAgents,
  listProjectChatChannels,
  listProjectChatMembers,
  listProjectChatMessages,
  listProjectChatMentionNotices,
  listProjectChatParticipants,
  sendProjectChatMessage,
  type ProjectChatAgent,
  type ProjectChatChannel,
  type ProjectChatMember,
  type ProjectChatMessage,
  type ProjectChatParticipant,
  type ProjectChatRealtimeStatus,
} from '@/api/projectChat'
import { useAppStore } from '@/stores/app'

const store = useAppStore()
const notice = useMessage()

const channels = ref<ProjectChatChannel[]>([])
const activeChannelId = ref<number | null>(null)
const members = ref<ProjectChatMember[]>([])
const messages = ref<ProjectChatMessage[]>([])
const draft = ref('')
const loadingChannels = ref(false)
const loadingMessages = ref(false)
const sending = ref(false)
const pageError = ref('')
const realtimeStatus = ref<ProjectChatRealtimeStatus>('connecting')
const messageViewport = ref<HTMLElement | null>(null)
const composerInput = ref<HTMLDivElement | null>(null)
const projectParticipants = ref<ProjectChatParticipant[]>([])
const mentionAgents = ref<ProjectChatAgent[]>([])
const mentionMenuOpen = ref(false)
const mentionQuery = ref('')
const mentionRangeStart = ref(0)
const mentionRangeEnd = ref(0)
const mentionActiveIndex = ref(0)
const privateChatDialogOpen = ref(false)
const privateChatTitle = ref('')
const participantSearch = ref('')
const selectedParticipantIds = ref<number[]>([])
const loadingParticipants = ref(false)
const creatingPrivateChat = ref(false)
const privateChatError = ref('')
const pulsingMentionIds = ref<Set<number>>(new Set())
const mentionNotices = ref<ProjectChatMessage[]>([])
const locatingMentionNotice = ref(false)

let loadGeneration = 0
let pollTimer: number | null = null
let realtimeClient: Awaited<ReturnType<typeof connectProjectChatRealtime>> = null
let refreshingChannelList = false
let mentionObserver: IntersectionObserver | null = null
const messageElements = new Map<number, HTMLElement>()
const claimingMentionIds = new Set<number>()
const resolvedMentionIds = new Set<number>()
const mentionPulseTimers = new Map<number, number>()

type MentionOption = {
  key: string
  type: 'all' | 'user' | 'agent'
  id: number | string
  name: string
  subtitle: string
}

type MessageSegment = {
  text: string
  targetType: 'all' | 'user' | 'agent' | null
}

const selectedMentions = ref<MentionOption[]>([])

const activeChannel = computed(() => (
  channels.value.find(item => item.id === activeChannelId.value) || null
))
const activeMentionNotice = computed(() => mentionNotices.value[0] || null)
const activeMentionNoticeTitle = computed(() => {
  const item = activeMentionNotice.value
  return item ? `${senderName(item)} 提到了你` : ''
})
const activeMentionNoticeDescription = computed(() => {
  const item = activeMentionNotice.value
  if (!item) return ''
  const channel = channels.value.find(candidate => candidate.id === item.channel_id)
  const channelTitle = channel ? channelDisplayTitle(channel) : '项目会话'
  const preview = item.content.replace(/\s+/g, ' ').trim().slice(0, 72)
  return `来自「${channelTitle}」${preview ? ` · ${preview}` : ''}`
})
const currentProjectName = computed(() => store.currentProject?.name || '当前项目')
const currentUserId = computed(() => Number(sessionStorage.getItem('current_user_id') || 0))
const canSend = computed(() => Boolean(activeChannel.value && draft.value.trim() && !sending.value))
const channelSections = computed(() => [
  {
    key: 'project',
    label: '项目会话',
    channels: channels.value.filter(channel => channel.channel_type !== 'private'),
  },
  {
    key: 'private',
    label: '私密会话',
    channels: channels.value.filter(channel => channel.channel_type === 'private'),
  },
].filter(sectionItem => sectionItem.channels.length))
const displayChannelTitle = computed(() => {
  if (loadingChannels.value) return '正在加载项目群'
  return activeChannel.value ? channelDisplayTitle(activeChannel.value) : '项目群'
})
const channelScopeLabel = computed(() => (
  activeChannel.value?.channel_type === 'private'
    ? '仅所选成员可见'
    : currentProjectName.value
))
const filteredParticipants = computed(() => {
  const keyword = participantSearch.value.trim().toLowerCase()
  return projectParticipants.value.filter(participant => {
    if (participant.user_id === currentUserId.value) return false
    if (!keyword) return true
    return `${participant.name} ${participant.title}`.toLowerCase().includes(keyword)
  })
})
const mentionOptions = computed<MentionOption[]>(() => [
  {
    key: 'all',
    type: 'all' as const,
    id: 'all',
    name: '全体成员',
    subtitle: '通知当前会话所有成员',
  },
  ...members.value
    .filter(member => member.user_id !== currentUserId.value)
    .map(member => ({
      key: `user:${member.user_id}`,
      type: 'user' as const,
      id: member.user_id,
      name: member.name,
      subtitle: member.title,
    })),
  ...mentionAgents.value
    .filter(agent => agent.enabled && agent.published && agent.model_ready)
    .map(agent => ({
      key: `agent:${agent.id}`,
      type: 'agent' as const,
      id: agent.id,
      name: agent.name,
      subtitle: agent.description || agent.category || '业务智能体',
    })),
])
const filteredMentionOptions = computed(() => {
  const keyword = mentionQuery.value.trim().toLowerCase()
  if (!keyword) return mentionOptions.value
  return mentionOptions.value.filter(option => (
    `${option.name} ${option.subtitle}`.toLowerCase().includes(keyword)
  ))
})
const canCreatePrivateChat = computed(() => (
  selectedParticipantIds.value.length > 0 && !creatingPrivateChat.value
))
const connectionLabel = computed(() => ({
  connected: '实时连接',
  connecting: '正在连接',
  polling: '定时刷新',
  disconnected: '连接恢复中',
}[realtimeStatus.value]))
const connectionDescription = computed(() => (
  realtimeStatus.value === 'connected'
    ? '新消息会实时到达当前页面'
    : '消息保存不受影响，页面会通过定时刷新补齐新消息'
))

function errorDetail(error: any, fallback: string) {
  return error?.response?.data?.detail || error?.message || fallback
}

function channelDisplayTitle(channel: ProjectChatChannel) {
  const title = channel.title?.trim()
  if (!title) return channel.channel_type === 'private' ? '私密会话' : '项目群'
  if (channel.channel_type === 'project' && title === `${currentProjectName.value}项目群`) {
    return '项目群'
  }
  return title
}

function compactTime(value: string) {
  const time = dayjs(value)
  return time.isSame(dayjs(), 'day') ? time.format('HH:mm') : time.format('M/D')
}

function messageTime(value: string | null) {
  if (!value) return ''
  const time = dayjs(value)
  return time.isSame(dayjs(), 'day') ? time.format('HH:mm') : time.format('M月D日 HH:mm')
}

function isOwnMessage(item: ProjectChatMessage) {
  return item.sender_type === 'user' && item.sender_user_id === currentUserId.value
}

function senderName(item: ProjectChatMessage) {
  if (item.sender_type === 'agent') {
    return String(item.metadata?.agent_name || item.sender?.name || item.sender_agent_id || '项目智能体')
  }
  if (item.sender_type === 'system') return '系统消息'
  return item.sender?.name || '项目成员'
}

function senderInitial(item: ProjectChatMessage) {
  return senderName(item).slice(0, 1)
}

function isMentioningCurrentUser(item: ProjectChatMessage) {
  return item.mentions.some(mention => (
    mention.target_type === 'all'
    || (mention.target_type === 'user' && mention.target_user_id === currentUserId.value)
  ))
}

function shouldClaimMentionAttention(item: ProjectChatMessage) {
  return currentUserId.value > 0
    && !isOwnMessage(item)
    && isMentioningCurrentUser(item)
    && !resolvedMentionIds.has(item.id)
}

function startMentionPulse(messageId: number) {
  const pulsing = new Set(pulsingMentionIds.value)
  pulsing.add(messageId)
  pulsingMentionIds.value = pulsing
  const previousTimer = mentionPulseTimers.get(messageId)
  if (previousTimer !== undefined) window.clearTimeout(previousTimer)
  mentionPulseTimers.set(
    messageId,
    window.setTimeout(() => {
      const remaining = new Set(pulsingMentionIds.value)
      remaining.delete(messageId)
      pulsingMentionIds.value = remaining
      mentionPulseTimers.delete(messageId)
    }, 2800),
  )
}

function removeMentionNotice(messageId: number) {
  mentionNotices.value = mentionNotices.value.filter(item => item.id !== messageId)
}

function queueMentionNotice(item: ProjectChatMessage) {
  if (
    item.sender_user_id === currentUserId.value
    || resolvedMentionIds.has(item.id)
  ) return
  mentionNotices.value = [
    item,
    ...mentionNotices.value.filter(existing => existing.id !== item.id),
  ].slice(0, 20)
}

async function viewActiveMentionNotice() {
  const item = activeMentionNotice.value
  if (!item || locatingMentionNotice.value) return
  locatingMentionNotice.value = true
  try {
    if (activeChannelId.value !== item.channel_id) {
      await activateChannel(item.channel_id)
    }
    if (!messages.value.some(message => message.id === item.id)) {
      mergeMessages([await getProjectChatMessage(item.id)])
    }
    await nextTick()
    const element = messageElements.get(item.id)
    const viewport = messageViewport.value
    if (!element || !viewport) return
    const viewportRect = viewport.getBoundingClientRect()
    const messageRect = element.getBoundingClientRect()
    const targetTop = viewport.scrollTop
      + messageRect.top
      - viewportRect.top
      - Math.max(0, (viewport.clientHeight - messageRect.height) / 2)
    viewport.scrollTo({ top: Math.max(0, targetTop), behavior: 'smooth' })
  } catch (error: any) {
    notice.error(errorDetail(error, '无法定位这条艾特消息。'))
  } finally {
    locatingMentionNotice.value = false
  }
}

async function claimMentionAttention(item: ProjectChatMessage, element: HTMLElement) {
  if (
    document.visibilityState !== 'visible'
    || claimingMentionIds.has(item.id)
    || !shouldClaimMentionAttention(item)
  ) return
  claimingMentionIds.add(item.id)
  try {
    const result = await claimProjectChatMention(item.id)
    resolvedMentionIds.add(item.id)
    removeMentionNotice(item.id)
    mentionObserver?.unobserve(element)
    if (result.first_seen) startMentionPulse(item.id)
  } catch {
    window.setTimeout(() => {
      if (!mentionObserver || !element.isConnected) return
      mentionObserver.unobserve(element)
      mentionObserver.observe(element)
    }, 1200)
  } finally {
    claimingMentionIds.delete(item.id)
  }
}

function registerMessageElement(item: ProjectChatMessage, element: unknown) {
  const previousElement = messageElements.get(item.id)
  if (!(element instanceof HTMLElement)) {
    if (previousElement) mentionObserver?.unobserve(previousElement)
    messageElements.delete(item.id)
    return
  }
  if (previousElement && previousElement !== element) {
    mentionObserver?.unobserve(previousElement)
  }
  messageElements.set(item.id, element)
  if (shouldClaimMentionAttention(item)) mentionObserver?.observe(element)
}

function refreshVisibleMentionAttention() {
  if (document.visibilityState !== 'visible' || !mentionObserver) return
  messageElements.forEach((element, messageId) => {
    const item = messages.value.find(message => message.id === messageId)
    if (!item || !shouldClaimMentionAttention(item)) return
    mentionObserver?.unobserve(element)
    mentionObserver?.observe(element)
  })
}

function agentRuntimeLabel(item: ProjectChatMessage) {
  if (item.sender_type !== 'agent') return ''
  const status = String(item.metadata?.runtime_status || '')
  return ({
    awaiting_permission: '等待确认',
    awaiting_external_result: '等待外部结果',
    interrupted: '已停止',
    exceed_max_iters: '已达迭代上限',
    error: '处理失败',
  } as Record<string, string>)[status] || ''
}

function mentionedAgentNames(item: ProjectChatMessage) {
  return item.mentions
    .filter(mention => mention.target_type === 'agent')
    .map(mention => mention.display_name)
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function messageSegments(item: ProjectChatMessage): MessageSegment[] {
  const mentionsByToken = new Map<string, 'all' | 'user' | 'agent'>()
  item.mentions.forEach(mention => {
    mentionsByToken.set(`@${mention.display_name}`, mention.target_type)
  })
  const tokens = [...mentionsByToken.keys()].sort((left, right) => right.length - left.length)
  if (!tokens.length) return [{ text: item.content, targetType: null }]
  const pattern = new RegExp(`(${tokens.map(escapeRegExp).join('|')})`, 'g')
  return item.content.split(pattern).filter(Boolean).map(text => ({
    text,
    targetType: mentionsByToken.get(text) || null,
  }))
}

const COMPOSER_MAX_LENGTH = 20000

function composerCaretOffset() {
  const editor = composerInput.value
  const selection = window.getSelection()
  if (!editor || !selection?.rangeCount) return draft.value.length
  const range = selection.getRangeAt(0)
  if (!editor.contains(range.commonAncestorContainer)) return draft.value.length
  const beforeCaret = range.cloneRange()
  beforeCaret.selectNodeContents(editor)
  beforeCaret.setEnd(range.endContainer, range.endOffset)
  return beforeCaret.toString().length
}

function setComposerCaretOffset(requestedOffset: number) {
  const editor = composerInput.value
  if (!editor) return
  const selection = window.getSelection()
  if (!selection) return
  const offset = Math.max(0, Math.min(requestedOffset, editor.textContent?.length || 0))
  const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT)
  let traversed = 0
  let textNode = walker.nextNode() as Text | null
  const range = document.createRange()
  while (textNode) {
    const nextOffset = traversed + textNode.data.length
    if (offset <= nextOffset) {
      const mentionToken = textNode.parentElement?.closest<HTMLElement>('[data-mention-key]')
      if (mentionToken) range.setStartAfter(mentionToken)
      else range.setStart(textNode, offset - traversed)
      range.collapse(true)
      selection.removeAllRanges()
      selection.addRange(range)
      return
    }
    traversed = nextOffset
    textNode = walker.nextNode() as Text | null
  }
  range.selectNodeContents(editor)
  range.collapse(false)
  selection.removeAllRanges()
  selection.addRange(range)
}

function composerMentionAtOffset(offset: number) {
  const editor = composerInput.value
  if (!editor) return false
  let traversed = 0
  return [...editor.childNodes].some(node => {
    const length = node.textContent?.length || 0
    const isMention = node instanceof HTMLElement && Boolean(node.dataset.mentionKey)
    const containsOffset = isMention && offset >= traversed && offset <= traversed + length
    traversed += length
    return containsOffset
  })
}

function syncSelectedMentionsFromEditor() {
  const editor = composerInput.value
  if (!editor) return
  const liveKeys = new Set(
    [...editor.querySelectorAll<HTMLElement>('[data-mention-key]')]
      .map(node => node.dataset.mentionKey)
      .filter((key): key is string => Boolean(key)),
  )
  selectedMentions.value = selectedMentions.value.filter(mention => liveKeys.has(mention.key))
}

function renderComposer(caretOffset = draft.value.length) {
  const editor = composerInput.value
  if (!editor) return
  const mentionsByToken = new Map<string, MentionOption>()
  selectedMentions.value.forEach(mention => {
    mentionsByToken.set(`@${mention.name}`, mention)
  })
  const tokens = [...mentionsByToken.keys()].sort((left, right) => right.length - left.length)
  const parts = tokens.length
    ? draft.value.split(new RegExp(`(${tokens.map(escapeRegExp).join('|')})`, 'g')).filter(Boolean)
    : [draft.value]
  const fragment = document.createDocumentFragment()
  parts.forEach(part => {
    const mention = mentionsByToken.get(part)
    if (!mention) {
      fragment.appendChild(document.createTextNode(part))
      return
    }
    const token = document.createElement('span')
    token.className = `composer-mention ${mention.type}`
    token.contentEditable = 'false'
    token.dataset.mentionKey = mention.key
    token.textContent = part
    fragment.appendChild(token)
  })
  editor.replaceChildren(fragment)
  setComposerCaretOffset(caretOffset)
}

function syncDraftFromEditor() {
  const editor = composerInput.value
  if (!editor) return
  const caret = composerCaretOffset()
  const content = (editor.textContent || '').replace(/\r/g, '')
  draft.value = content.slice(0, COMPOSER_MAX_LENGTH)
  syncSelectedMentionsFromEditor()
  if (content.length > COMPOSER_MAX_LENGTH) {
    renderComposer(Math.min(caret, COMPOSER_MAX_LENGTH))
  }
}

function clearComposer() {
  draft.value = ''
  selectedMentions.value = []
  composerInput.value?.replaceChildren()
  closeMentionMenu()
}

function closeMentionMenu() {
  mentionMenuOpen.value = false
  mentionQuery.value = ''
  mentionActiveIndex.value = 0
}

function deferCloseMentionMenu() {
  window.setTimeout(() => closeMentionMenu(), 120)
}

function updateMentionState() {
  syncDraftFromEditor()
  const input = composerInput.value
  if (!input) return closeMentionMenu()
  const caret = composerCaretOffset()
  if (composerMentionAtOffset(caret)) return closeMentionMenu()
  const beforeCaret = draft.value.slice(0, caret)
  const atIndex = beforeCaret.lastIndexOf('@')
  if (atIndex < 0) return closeMentionMenu()
  const query = beforeCaret.slice(atIndex + 1)
  if (/\s/.test(query) || query.length > 40) return closeMentionMenu()
  mentionRangeStart.value = atIndex
  mentionRangeEnd.value = caret
  if (mentionQuery.value !== query) mentionActiveIndex.value = 0
  mentionQuery.value = query
  mentionMenuOpen.value = true
}

async function selectMention(option: MentionOption) {
  const before = draft.value.slice(0, mentionRangeStart.value)
  const after = draft.value.slice(mentionRangeEnd.value)
  const inserted = `@${option.name} `
  draft.value = `${before}${inserted}${after}`
  if (!selectedMentions.value.some(item => item.key === option.key)) {
    selectedMentions.value = [...selectedMentions.value, option]
  }
  const caret = before.length + inserted.length
  closeMentionMenu()
  await nextTick()
  composerInput.value?.focus()
  renderComposer(caret)
}

function insertComposerText(value: string) {
  const editor = composerInput.value
  const selection = window.getSelection()
  if (!editor || !selection) return
  let range: Range
  if (selection.rangeCount && editor.contains(selection.getRangeAt(0).commonAncestorContainer)) {
    range = selection.getRangeAt(0)
  } else {
    range = document.createRange()
    range.selectNodeContents(editor)
    range.collapse(false)
  }
  const currentLength = editor.textContent?.length || 0
  const availableLength = Math.max(
    0,
    COMPOSER_MAX_LENGTH - currentLength + range.toString().length,
  )
  const safeValue = value.slice(0, availableLength)
  range.deleteContents()
  const textNode = document.createTextNode(safeValue)
  range.insertNode(textNode)
  range.setStartAfter(textNode)
  range.collapse(true)
  selection.removeAllRanges()
  selection.addRange(range)
  updateMentionState()
}

function openMentionMenu() {
  const input = composerInput.value
  if (!input) return
  input.focus()
  insertComposerText('@')
}

function handleComposerPaste(event: ClipboardEvent) {
  event.preventDefault()
  insertComposerText(event.clipboardData?.getData('text/plain').replace(/\r\n?/g, '\n') || '')
}

function handleComposerKeydown(event: KeyboardEvent) {
  if (event.isComposing) return
  if (mentionMenuOpen.value) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      mentionActiveIndex.value = Math.min(
        mentionActiveIndex.value + 1,
        Math.max(0, filteredMentionOptions.value.length - 1),
      )
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      mentionActiveIndex.value = Math.max(mentionActiveIndex.value - 1, 0)
      return
    }
    if (
      ((event.key === 'Enter' && !event.shiftKey) || event.key === 'Tab')
      && filteredMentionOptions.value.length
    ) {
      event.preventDefault()
      void selectMention(filteredMentionOptions.value[mentionActiveIndex.value])
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      closeMentionMenu()
      return
    }
  }
  if (event.key === 'Enter' && event.shiftKey) {
    event.preventDefault()
    insertComposerText('\n')
    return
  }
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void sendMessage()
  }
}

function isNearMessageBottom() {
  const viewport = messageViewport.value
  if (!viewport) return true
  return viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 120
}

async function scrollMessagesToBottom(smooth = false) {
  await nextTick()
  const viewport = messageViewport.value
  if (!viewport) return
  viewport.scrollTo({
    top: viewport.scrollHeight,
    behavior: smooth ? 'smooth' : 'auto',
  })
}

function mergeMessages(incoming: ProjectChatMessage[], forceScroll = false) {
  if (!incoming.length) return
  const shouldScroll = forceScroll || isNearMessageBottom()
  const byId = new Map(messages.value.map(item => [item.id, item]))
  incoming.forEach(item => byId.set(item.id, item))
  messages.value = [...byId.values()].sort((left, right) => left.id - right.id)
  const latest = messages.value[messages.value.length - 1]
  channels.value = channels.value.map(channel => (
    channel.id === latest.channel_id
      ? { ...channel, last_message: latest, last_message_at: latest.created_at }
      : channel
  ))
  if (shouldScroll) void scrollMessagesToBottom(forceScroll)
}

async function fetchMessages(channelId: number, replace = false) {
  const latestId = replace ? undefined : messages.value[messages.value.length - 1]?.id
  const rows = await listProjectChatMessages(channelId, { afterId: latestId, limit: 100 })
  if (activeChannelId.value !== channelId) return
  if (replace) {
    messages.value = rows
    await scrollMessagesToBottom()
  } else {
    mergeMessages(rows)
  }
}

async function activateChannel(channelId: number) {
  if (activeChannelId.value === channelId && messages.value.length) return
  if (activeChannelId.value !== channelId) {
    clearComposer()
  }
  activeChannelId.value = channelId
  loadingMessages.value = true
  pageError.value = ''
  messages.value = []
  members.value = []
  try {
    const [loadedMessages, loadedMembers] = await Promise.all([
      listProjectChatMessages(channelId, { limit: 100 }),
      listProjectChatMembers(channelId),
    ])
    if (activeChannelId.value !== channelId) return
    messages.value = loadedMessages
    members.value = loadedMembers
    await scrollMessagesToBottom()
  } catch (error: any) {
    pageError.value = errorDetail(error, '无法加载项目群聊。')
  } finally {
    if (activeChannelId.value === channelId) loadingMessages.value = false
  }
}

async function loadPrivateChatParticipants() {
  const projectId = store.currentProjectId
  if (!projectId || loadingParticipants.value) return
  loadingParticipants.value = true
  privateChatError.value = ''
  try {
    projectParticipants.value = await listProjectChatParticipants(projectId)
  } catch (error: any) {
    privateChatError.value = errorDetail(error, '无法加载项目成员。')
  } finally {
    loadingParticipants.value = false
  }
}

async function loadMentionAgents() {
  try {
    mentionAgents.value = await listProjectChatAgents()
  } catch {
    mentionAgents.value = []
  }
}

function openPrivateChatDialog() {
  privateChatTitle.value = ''
  participantSearch.value = ''
  selectedParticipantIds.value = []
  privateChatError.value = ''
  privateChatDialogOpen.value = true
  void loadPrivateChatParticipants()
}

function closePrivateChatDialog() {
  if (creatingPrivateChat.value) return
  privateChatDialogOpen.value = false
}

async function createPrivateChat() {
  const projectId = store.currentProjectId
  if (!projectId || !canCreatePrivateChat.value) return
  creatingPrivateChat.value = true
  privateChatError.value = ''
  try {
    const created = await createPrivateProjectChatChannel(projectId, {
      title: privateChatTitle.value.trim() || undefined,
      participant_user_ids: selectedParticipantIds.value,
    })
    channels.value = await listProjectChatChannels(projectId)
    privateChatDialogOpen.value = false
    await activateChannel(created.id)
    stopRealtime()
    realtimeStatus.value = 'connecting'
    void startRealtime(projectId, loadGeneration)
    notice.success('私密会话已创建。')
  } catch (error: any) {
    privateChatError.value = errorDetail(error, '创建私密会话失败。')
  } finally {
    creatingPrivateChat.value = false
  }
}

function stopRealtime() {
  if (pollTimer !== null) window.clearInterval(pollTimer)
  pollTimer = null
  realtimeClient?.disconnect()
  realtimeClient = null
}

function startPolling() {
  if (pollTimer !== null) window.clearInterval(pollTimer)
  pollTimer = window.setInterval(() => {
    if (activeChannelId.value && !loadingMessages.value) {
      void fetchMessages(activeChannelId.value).catch(() => undefined)
    }
  }, 5000)
}

async function refreshChannelListFromRealtime(projectId: string, generation: number) {
  if (refreshingChannelList || generation !== loadGeneration) return
  refreshingChannelList = true
  try {
    const rows = await listProjectChatChannels(projectId)
    if (generation !== loadGeneration) return
    channels.value = rows
    const activeStillVisible = rows.some(channel => channel.id === activeChannelId.value)
    if (!activeStillVisible && rows[0]) await activateChannel(rows[0].id)
    stopRealtime()
    realtimeStatus.value = 'connecting'
    await startRealtime(projectId, generation)
  } catch {
    if (generation === loadGeneration) realtimeStatus.value = 'polling'
  } finally {
    refreshingChannelList = false
  }
}

async function startRealtime(projectId: string, generation: number) {
  try {
    const client = await connectProjectChatRealtime(projectId, {
      onMessage: incoming => {
        if (generation !== loadGeneration || incoming.channel_id !== activeChannelId.value) return
        mergeMessages([incoming])
      },
      onStatus: status => {
        if (generation === loadGeneration) realtimeStatus.value = status
      },
      onChannelsChanged: () => {
        if (generation === loadGeneration) {
          void refreshChannelListFromRealtime(projectId, generation)
        }
      },
      onMention: incoming => {
        if (generation !== loadGeneration || incoming.sender_user_id === currentUserId.value) return
        if (incoming.channel_id === activeChannelId.value) mergeMessages([incoming])
        queueMentionNotice(incoming)
      },
    })
    if (generation !== loadGeneration) {
      client?.disconnect()
      return
    }
    realtimeClient = client
  } catch {
    if (generation === loadGeneration) realtimeStatus.value = 'polling'
  }
  if (generation === loadGeneration) startPolling()
}

async function loadProjectChat(projectId: string) {
  const generation = ++loadGeneration
  stopRealtime()
  privateChatDialogOpen.value = false
  projectParticipants.value = []
  selectedParticipantIds.value = []
  channels.value = []
  activeChannelId.value = null
  members.value = []
  messages.value = []
  mentionNotices.value = []
  locatingMentionNotice.value = false
  clearComposer()
  pageError.value = ''
  realtimeStatus.value = 'connecting'
  if (!projectId) return
  loadingChannels.value = true
  try {
    const [rows, unseenNotices] = await Promise.all([
      listProjectChatChannels(projectId),
      listProjectChatMentionNotices(projectId),
      loadMentionAgents(),
    ])
    if (generation !== loadGeneration) return
    channels.value = rows
    mentionNotices.value = unseenNotices
    const firstChannel = rows[0]
    if (firstChannel) await activateChannel(firstChannel.id)
    if (generation === loadGeneration) void startRealtime(projectId, generation)
  } catch (error: any) {
    if (generation === loadGeneration) {
      pageError.value = errorDetail(error, '无法初始化项目群聊。')
      realtimeStatus.value = 'polling'
    }
  } finally {
    if (generation === loadGeneration) loadingChannels.value = false
  }
}

function reloadProjectChat() {
  void loadProjectChat(store.currentProjectId)
}

async function manualRefresh() {
  if (!activeChannelId.value) return
  try {
    await fetchMessages(activeChannelId.value)
    notice.success('已刷新群聊消息。')
  } catch (error: any) {
    notice.error(errorDetail(error, '刷新消息失败。'))
  }
}

async function sendMessage() {
  syncDraftFromEditor()
  const content = draft.value.trim()
  const channelId = activeChannelId.value
  if (!content || !channelId || sending.value) return
  sending.value = true
  try {
    const created = await sendProjectChatMessage(channelId, content, {
      mentionAll: selectedMentions.value.some(mention => mention.type === 'all'),
      mentionedUserIds: selectedMentions.value
        .filter(mention => mention.type === 'user')
        .map(mention => Number(mention.id)),
      mentionedAgentIds: selectedMentions.value
        .filter(mention => mention.type === 'agent')
        .map(mention => String(mention.id)),
    })
    clearComposer()
    mergeMessages([created], true)
  } catch (error: any) {
    notice.error(errorDetail(error, '发送消息失败。'))
  } finally {
    sending.value = false
  }
}

onMounted(() => {
  mentionObserver = new IntersectionObserver(
    entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return
        const element = entry.target as HTMLElement
        const messageId = Number(element.dataset.messageId || 0)
        const item = messages.value.find(message => message.id === messageId)
        if (item) void claimMentionAttention(item, element)
      })
    },
    {
      root: messageViewport.value,
      threshold: 0.01,
    },
  )
  messageElements.forEach((element, messageId) => {
    const item = messages.value.find(message => message.id === messageId)
    if (item && shouldClaimMentionAttention(item)) mentionObserver?.observe(element)
  })
  document.addEventListener('visibilitychange', refreshVisibleMentionAttention)
})

watch(
  () => store.currentProjectId,
  projectId => void loadProjectChat(projectId),
  { immediate: true },
)

onBeforeUnmount(() => {
  loadGeneration += 1
  stopRealtime()
  document.removeEventListener('visibilitychange', refreshVisibleMentionAttention)
  mentionObserver?.disconnect()
  mentionObserver = null
  messageElements.clear()
  mentionPulseTimers.forEach(timer => window.clearTimeout(timer))
  mentionPulseTimers.clear()
})
</script>

<style scoped>
.project-chat-shell {
  --chat-ink: #102c30;
  --chat-muted: #61757a;
  --chat-accent: #0b756e;
  position: relative;
  display: grid;
  grid-template-columns: 19rem minmax(32rem, 1fr) 23rem;
  gap: 0.55rem;
  height: calc(100dvh - var(--header-height) - 1.5rem);
  min-height: 38rem;
  overflow: hidden;
  color: var(--chat-ink);
}

.channel-rail,
.chat-stage,
.chat-context {
  min-width: 0;
  overflow: hidden;
  border: 1px solid rgba(19, 54, 58, 0.11);
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 18px 44px rgba(29, 55, 50, 0.06);
}

.channel-rail {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  border-radius: 0.75rem 0.35rem 0.35rem 0.75rem;
}

.rail-heading,
.chat-heading {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  border-bottom: 1px solid rgba(19, 54, 58, 0.09);
}

.rail-heading { padding: 0.9rem; }
.rail-title { min-width: 0; flex: 1; }
.rail-title p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.new-private-chat {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 2.25rem;
  height: 2.25rem;
  border: 1px solid rgba(11, 117, 110, 0.2);
  border-radius: 0.5rem;
  background: #f1f8f6;
  color: var(--chat-accent);
  cursor: pointer;
  transition: border-color 180ms ease, background 180ms ease, transform 180ms ease;
}
.new-private-chat:hover { border-color: rgba(11, 117, 110, 0.42); background: #e3f2ee; }
.new-private-chat:active { transform: translateY(1px); }
.new-private-chat:focus-visible { outline: 2px solid rgba(11, 117, 110, 0.35); outline-offset: 2px; }

.heading-icon,
.chat-channel-mark,
.boundary-icon {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 0.55rem;
  background: #e5f3f0;
  color: var(--chat-accent);
}

.rail-heading h1,
.chat-heading h1,
.chat-context h2,
.chat-context h3 {
  margin: 0;
  color: var(--chat-ink);
}

.rail-heading h1 { font-size: 15px; line-height: 1.25; font-weight: 800; }

.rail-heading p,
.chat-heading p,
.chat-context p {
  margin: 0.2rem 0 0;
  color: var(--chat-muted);
  font-size: 12px;
  line-height: 1.45;
}

.channel-section-label,
.context-eyebrow {
  color: #6c7f83;
  font-size: 12px;
  font-weight: 750;
  letter-spacing: 0.04em;
}

.channel-list { min-height: 0; overflow: auto; padding: 0.65rem 0.5rem; }
.channel-section-label { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; padding: 0.65rem 0.45rem 0.4rem; }
.channel-section-label:first-of-type { padding-top: 0; }
.channel-section-label em { color: #839491; font-size: 12px; font-style: normal; font-variant-numeric: tabular-nums; }
.channel-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 0.5rem;
  align-items: center;
  width: 100%;
  min-height: 3.8rem;
  padding: 0.55rem;
  border: 1px solid transparent;
  border-radius: 0.55rem;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 180ms ease, border-color 180ms ease, transform 180ms ease;
}
.channel-item:hover { border-color: rgba(11, 117, 110, 0.14); background: #f3f8f6; }
.channel-item:active { transform: translateY(1px); }
.channel-item:focus-visible { outline: 2px solid rgba(11, 117, 110, 0.35); outline-offset: 2px; }
.channel-item.active { border-color: rgba(11, 117, 110, 0.24); background: #eaf5f2; box-shadow: inset 3px 0 0 var(--chat-accent); }
.channel-symbol { color: var(--chat-accent); }
.channel-item.private .channel-symbol { color: #5b706f; }
.channel-copy { min-width: 0; display: grid; gap: 0.2rem; }
.channel-copy strong { overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.channel-copy small { overflow: hidden; color: var(--chat-muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.channel-item time { display: block; align-self: start; color: #819095; font-size: 12px; font-variant-numeric: tabular-nums; }
.rail-foot { display: flex; gap: 0.45rem; align-items: flex-start; padding: 0.7rem 0.8rem; border-top: 1px solid rgba(19, 54, 58, 0.08); color: #6c7f83; font-size: 12px; line-height: 1.4; }
.rail-empty { padding: 0.9rem 0.4rem; color: var(--chat-muted); font-size: 12px; }
.channel-skeleton { display: grid; grid-template-columns: 1.5rem 1fr; gap: 0.5rem; padding: 0.65rem; }
.channel-skeleton i { grid-row: 1 / 3; width: 1.5rem; height: 1.5rem; border-radius: 0.4rem; }
.channel-skeleton span { height: 0.8rem; width: 70%; }
.channel-skeleton small { height: 0.7rem; width: 90%; }
.channel-skeleton i,
.channel-skeleton span,
.channel-skeleton small,
.message-placeholder i,
.message-placeholder span {
  display: block;
  background: linear-gradient(90deg, #edf2f0, #f8faf9, #edf2f0);
  background-size: 200% 100%;
  animation: chat-shimmer 1.4s linear infinite;
}

.chat-stage {
  display: flex;
  height: 100%;
  flex-direction: column;
  border-radius: 0.75rem;
}

.chat-heading {
  justify-content: space-between;
  min-height: 4.5rem;
  padding: 0.7rem 1.1rem;
  background: rgba(255, 255, 255, 0.97);
}

.chat-heading-main { display: flex; align-items: center; gap: 0.7rem; min-width: 0; }
.chat-heading-main > div:last-child { min-width: 0; }
.chat-heading h1 { overflow: hidden; font-size: 17px; line-height: 1.25; font-weight: 800; text-overflow: ellipsis; white-space: nowrap; }
.chat-heading p { display: flex; min-width: 0; gap: 0.4rem; align-items: center; white-space: nowrap; }
.current-project-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.connection-state {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 0.4rem;
  min-height: 2rem;
  padding: 0 0.65rem;
  border-radius: 0.45rem;
  background: #f1f5f3;
  color: #63777b;
  font-size: 12px;
  font-weight: 700;
}

.connection-state.connected { background: #e6f5ef; color: #11715d; }
.connection-state.connecting { color: #8a6c20; }

.chat-alert {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 0.55rem;
  margin: 0.65rem 1rem 0;
  padding: 0.65rem 0.75rem;
  border: 1px solid #efd2c6;
  border-radius: 0.45rem;
  background: #fff7f3;
  color: #8b452c;
  font-size: 12px;
}

.chat-alert span { min-width: 0; flex: 1; }
.chat-alert button,
.polling-note button {
  border: 0;
  background: transparent;
  color: var(--chat-accent);
  font: inherit;
  font-weight: 750;
  cursor: pointer;
}

.message-viewport {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 1.35rem clamp(1.1rem, 4vw, 4.5rem) 1.75rem;
  background:
    radial-gradient(circle at 8% 2%, rgba(11, 117, 110, 0.065), transparent 22rem),
    radial-gradient(circle at 94% 96%, rgba(104, 139, 132, 0.05), transparent 24rem),
    #f7faf8;
  scroll-behavior: smooth;
}

.chat-message {
  display: flex;
  gap: 0.65rem;
  align-items: flex-start;
  max-width: min(46rem, 84%);
  margin-bottom: 1rem;
}

.chat-message.own { flex-direction: row-reverse; margin-left: auto; }
.sender-avatar,
.member-avatar {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 2rem;
  height: 2rem;
  border-radius: 0.5rem;
  background: #dfeae7;
  color: #21484a;
  font-size: 12px;
  font-weight: 800;
}
.chat-message.own .sender-avatar { background: #0b6865; color: #fff; }
.chat-message.agent .sender-avatar { background: #e4f1ee; color: var(--chat-accent); }

.message-body { min-width: 0; display: grid; gap: 0.35rem; }
.message-meta { display: flex; align-items: center; gap: 0.45rem; color: #718287; font-size: 12px; }
.chat-message.own .message-meta { justify-content: flex-end; }
.message-meta strong { color: #385257; font-size: 12px; }
.message-meta time { font-variant-numeric: tabular-nums; }
.agent-label,
.owner-label,
.runtime-label {
  padding: 0.1rem 0.35rem;
  border-radius: 0.25rem;
  background: #e8f3f0;
  color: var(--chat-accent);
  font-size: 12px;
  font-weight: 700;
  font-style: normal;
}
.runtime-label { background: #fff2df; color: #9b5e16; }

.message-content {
  padding: 0.7rem 0.85rem;
  border: 1px solid rgba(19, 54, 58, 0.1);
  border-radius: 0.35rem 0.75rem 0.75rem 0.75rem;
  background: #fff;
  color: #213b3f;
  box-shadow: 0 8px 22px rgba(30, 56, 52, 0.055);
  font-size: 14px;
  line-height: 1.65;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.chat-message.own .message-content {
  border-color: #0a6562;
  border-radius: 0.75rem 0.35rem 0.75rem 0.75rem;
  background: #0a5655;
  color: #fff;
}
.chat-message.mentioned:not(.own) .message-content {
  border-color: rgba(11, 117, 110, 0.42);
  box-shadow: 0 10px 26px rgba(11, 117, 110, 0.1);
}
.chat-message.mention-pulse:not(.own) .message-content {
  transform-origin: left center;
  animation: mention-attention-pulse 640ms ease-in-out 4;
  will-change: transform, background-color, border-color, box-shadow;
}
.chat-message.failed .message-content { border-color: #e7bbaa; background: #fff8f4; color: #7e3c28; }
.message-mention {
  display: inline;
  border-radius: 0.28rem;
  padding: 0.08rem 0.24rem;
  background: #e3f2ee;
  color: #087169;
  font-weight: 760;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
}
.message-mention.agent { background: #e9eefb; color: #3d5ca4; }
.message-mention.all { background: #e6f0ff; color: #1769bd; }
.chat-message.own .message-mention { background: rgba(255, 255, 255, 0.18); color: #fff; }
.agent-request-note {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  color: #5d7377;
  font-size: 12px;
  line-height: 1.45;
}
.chat-message.own .agent-request-note { justify-content: flex-end; }

.chat-empty {
  display: grid;
  justify-items: center;
  align-content: center;
  min-height: 100%;
  padding: 2rem;
  text-align: center;
}
.empty-robot { display: grid; place-items: center; width: 4.5rem; height: 4.5rem; margin-bottom: 1rem; border-radius: 1rem; background: #e5f2ef; color: var(--chat-accent); box-shadow: 0 14px 34px rgba(11, 117, 110, 0.12); }
.chat-empty h3 { margin: 0; color: var(--chat-ink); font-size: 17px; }
.chat-empty p { max-width: 30rem; margin: 0.55rem 0 0; color: var(--chat-muted); font-size: 13px; line-height: 1.65; text-wrap: pretty; }

.message-loading { padding-top: 0.5rem; }
.message-placeholder { display: flex; gap: 0.65rem; align-items: flex-start; margin-bottom: 1rem; }
.message-placeholder.own { flex-direction: row-reverse; }
.message-placeholder i { width: 2rem; height: 2rem; border-radius: 0.5rem; }
.message-placeholder span { width: min(26rem, 65%); height: 4.3rem; border-radius: 0.7rem; }

.message-composer {
  flex: 0 0 auto;
  padding: 0 1rem 1rem;
  border-top: 0;
  background: linear-gradient(180deg, rgba(247, 250, 248, 0), #fff 32%);
}
.mention-notice {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 0.6rem;
  min-height: 3.15rem;
  margin-bottom: 0.5rem;
  padding: 0.48rem 0.55rem 0.48rem 0.65rem;
  border: 1px solid rgba(11, 117, 110, 0.2);
  border-radius: 0.65rem;
  background: #edf7f4;
  box-shadow: 0 10px 24px rgba(25, 69, 61, 0.08);
  animation: mention-notice-enter 180ms ease-out;
}
.mention-notice-icon {
  display: grid;
  place-items: center;
  width: 2rem;
  height: 2rem;
  border-radius: 50%;
  background: #d9eee9;
  color: #0b756e;
}
.mention-notice-copy {
  display: grid;
  min-width: 0;
  gap: 0.08rem;
}
.mention-notice-copy strong,
.mention-notice-copy > span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mention-notice-copy strong { color: #173d40; font-size: 13px; font-weight: 760; }
.mention-notice-copy > span { color: #5b7477; font-size: 12px; }
.mention-notice-count {
  color: #0b6b65;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  font-weight: 700;
}
.mention-notice-locate {
  min-width: 3.6rem;
  min-height: 2rem;
  padding: 0 0.65rem;
  border: 1px solid rgba(11, 117, 110, 0.28);
  border-radius: 0.42rem;
  background: #fff;
  color: #0b6964;
  font: inherit;
  font-size: 12px;
  font-weight: 750;
  cursor: pointer;
  transition: transform 180ms ease, border-color 180ms ease, background 180ms ease;
}
.mention-notice-locate:hover:not(:disabled) { border-color: rgba(11, 117, 110, 0.5); background: #f7fbfa; }
.mention-notice-locate:active:not(:disabled) { transform: translateY(1px); }
.mention-notice-locate:focus-visible { outline: 2px solid rgba(11, 117, 110, 0.32); outline-offset: 2px; }
.mention-notice-locate:disabled { opacity: 0.55; cursor: wait; }
.polling-note { display: flex; justify-content: center; gap: 0.35rem; padding: 0.4rem 1rem 0; color: #7d6b39; font-size: 12px; line-height: 1.4; }
.message-composer form {
  position: relative;
  padding: 0.65rem 0.7rem 0.7rem;
  border: 1px solid rgba(19, 54, 58, 0.16);
  border-radius: 0.75rem;
  background: #fff;
  box-shadow: 0 15px 34px rgba(28, 63, 57, 0.09);
  transition: border-color 180ms ease, box-shadow 180ms ease;
}
.mention-menu {
  position: absolute;
  z-index: 20;
  bottom: calc(100% + 0.5rem);
  left: 0.7rem;
  width: min(20rem, calc(100% - 1.4rem));
  overflow: hidden;
  border: 1px solid rgba(19, 54, 58, 0.17);
  border-radius: 0.7rem;
  background: #fff;
  box-shadow: 0 18px 48px rgba(16, 44, 48, 0.18);
}
.mention-options { max-height: 17rem; overflow: auto; padding: 0.35rem; }
.mention-option {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 0.65rem;
  width: 100%;
  min-height: 3.35rem;
  padding: 0.45rem 0.55rem;
  border: 0;
  border-radius: 0.5rem;
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.mention-option:hover,
.mention-option.active { background: #eaf5f2; }
.mention-option:focus-visible { outline: 2px solid rgba(11, 117, 110, 0.35); outline-offset: -1px; }
.mention-avatar {
  display: grid;
  place-items: center;
  width: 2rem;
  height: 2rem;
  border-radius: 0.48rem;
  background: #e5eeeb;
  color: #36575b;
}
.mention-avatar.agent { background: #e8edfa; color: #4862a2; }
.mention-avatar.all { border-radius: 50%; background: #e6f0ff; color: #1677c8; }
.mention-copy { min-width: 0; display: grid; gap: 0.12rem; }
.mention-copy strong,
.mention-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mention-copy strong { color: #29474b; font-size: 13px; }
.mention-copy small { color: var(--chat-muted); font-size: 12px; }
.mention-empty { display: grid; min-height: 5.5rem; place-items: center; color: var(--chat-muted); font-size: 13px; }
.message-composer form:focus-within { border-color: rgba(11, 117, 110, 0.5); box-shadow: 0 17px 38px rgba(28, 73, 65, 0.12), 0 0 0 3px rgba(11, 117, 110, 0.07); }
.composer-editor {
  display: block;
  width: 100%;
  min-height: 3.5rem;
  max-height: 10rem;
  overflow-y: auto;
  padding: 0.45rem 0.5rem;
  border: 0;
  border-radius: 0.4rem;
  outline: none;
  color: var(--chat-ink);
  font: inherit;
  font-size: 14px;
  line-height: 1.55;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
  cursor: text;
}
.composer-editor[data-empty='true']::before {
  color: #879599;
  content: attr(data-placeholder);
  pointer-events: none;
}
.composer-editor.disabled { background: #f3f5f4; cursor: not-allowed; }
.composer-mention {
  border-radius: 0.2rem;
  color: #1677c8;
  font-weight: 650;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
}
.composer-mention.agent { color: #4c65a4; }
.composer-mention.all { color: #1769bd; }
.composer-actions { display: flex; justify-content: space-between; align-items: center; gap: 1rem; margin-top: 0.35rem; padding-left: 0.5rem; }
.composer-tools { min-width: 0; display: flex; align-items: center; gap: 0.7rem; }
.mention-trigger {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  width: 2rem;
  min-height: 2rem;
  padding: 0;
  border: 1px solid rgba(11, 117, 110, 0.18);
  border-radius: 0.42rem;
  background: #f2f8f6;
  color: #176d67;
  font: inherit;
  font-size: 12px;
  font-weight: 750;
  cursor: pointer;
}
.mention-trigger:hover:not(:disabled) { border-color: rgba(11, 117, 110, 0.35); background: #e6f3ef; }
.mention-trigger:disabled { opacity: 0.5; cursor: not-allowed; }
.composer-hint { display: flex; gap: 0.85rem; color: #718287; font-size: 12px; }
.send-message {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  min-width: 5.6rem;
  height: 2.35rem;
  border: 1px solid #0b6964;
  border-radius: 0.45rem;
  background: #0b6964;
  color: #fff;
  font: inherit;
  font-size: 13px;
  font-weight: 750;
  cursor: pointer;
  transition: transform 180ms ease, background 180ms ease, box-shadow 180ms ease;
}
.send-message:hover:not(:disabled) { background: #085b58; box-shadow: 0 9px 20px rgba(11, 105, 100, 0.2); transform: translateY(-1px); }
.send-message:active:not(:disabled) { transform: translateY(1px); }
.send-message:focus-visible { outline: 2px solid rgba(11, 117, 110, 0.35); outline-offset: 2px; }
.send-message:disabled { opacity: 0.48; cursor: not-allowed; }

.chat-context {
  display: grid;
  align-content: start;
  overflow: auto;
  border-radius: 0.35rem 0.75rem 0.75rem 0.35rem;
}
.context-section { padding: 0.9rem; border-bottom: 1px solid rgba(19, 54, 58, 0.09); }
.chat-context h2 { margin-top: 0.35rem; font-size: 16px; line-height: 1.35; }
.chat-context h3 { font-size: 14px; line-height: 1.35; }
.group-summary dl { display: grid; gap: 0.5rem; margin: 1rem 0 0; }
.group-summary dl div { display: flex; justify-content: space-between; gap: 1rem; font-size: 12px; }
.group-summary dt { color: var(--chat-muted); }
.group-summary dd { margin: 0; color: #29464a; font-weight: 700; }
.member-section header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.member-section header > span { color: var(--chat-muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.member-section h3 { margin-top: 0.25rem; }
.member-list { display: grid; gap: 0.35rem; margin-top: 0.8rem; }
.member-row { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 0.6rem; align-items: center; padding: 0.45rem 0; }
.member-avatar { width: 1.9rem; height: 1.9rem; border-radius: 0.45rem; }
.member-row > div:nth-child(2) { min-width: 0; display: grid; gap: 0.15rem; }
.member-row strong { display: flex; align-items: center; gap: 0.35rem; overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.member-row strong em { color: var(--chat-accent); font-size: 12px; font-style: normal; }
.member-row small { overflow: hidden; color: var(--chat-muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.owner-label { background: #f1f4f2; color: #607377; }
.agent-boundary { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 0.7rem; background: #f4f9f7; }
.agent-boundary p { line-height: 1.6; }

.private-chat-dialog {
  --chat-ink: #102c30;
  --chat-muted: #61757a;
  --chat-accent: #0b756e;
  width: min(44rem, calc(100vw - 2rem));
  overflow: hidden;
  border: 1px solid rgba(19, 54, 58, 0.14);
  border-radius: 0.9rem;
  background: #fff;
  box-shadow: 0 28px 80px rgba(16, 44, 48, 0.2);
}
.private-chat-dialog > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  padding: 1.25rem 1.35rem 1.05rem;
  border-bottom: 1px solid rgba(19, 54, 58, 0.09);
  background: radial-gradient(circle at 6% 0, rgba(11, 117, 110, 0.08), transparent 18rem), #fbfcfc;
}
.private-chat-dialog > header span { color: var(--chat-accent); font-size: 12px; font-weight: 800; letter-spacing: 0.05em; }
.private-chat-dialog > header h2 { margin: 0.25rem 0 0; color: var(--chat-ink); font-size: 20px; line-height: 1.25; }
.private-chat-dialog > header p { max-width: 38rem; margin: 0.35rem 0 0; color: var(--chat-muted); font-size: 13px; line-height: 1.55; }
.private-chat-dialog > header button {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  width: 2.3rem;
  height: 2.3rem;
  border: 1px solid rgba(19, 54, 58, 0.13);
  border-radius: 0.5rem;
  background: #fff;
  color: #50696d;
  cursor: pointer;
}
.private-chat-dialog > header button:hover:not(:disabled) { background: #edf5f2; }
.private-chat-dialog > header button:focus-visible { outline: 2px solid rgba(11, 117, 110, 0.35); outline-offset: 2px; }
.private-chat-dialog button:disabled { opacity: 0.5; cursor: not-allowed; }
.private-chat-form { display: grid; gap: 1rem; padding: 1.1rem 1.35rem 1.2rem; }
.private-chat-name { display: grid; gap: 0.45rem; color: #36575b; font-size: 12px; font-weight: 750; }
.private-chat-name > span { display: flex; align-items: center; gap: 0.4rem; }
.private-chat-name em { color: #849491; font-size: 12px; font-style: normal; font-weight: 500; }
.private-chat-name input,
.participant-search input {
  min-width: 0;
  border: 0;
  outline: 0;
  color: var(--chat-ink);
  background: transparent;
  font: inherit;
  font-size: 13px;
}
.private-chat-name > input {
  width: 100%;
  height: 2.55rem;
  padding: 0 0.75rem;
  border: 1px solid rgba(19, 54, 58, 0.16);
  border-radius: 0.5rem;
  background: #fff;
}
.private-chat-name > input:focus { border-color: rgba(11, 117, 110, 0.55); box-shadow: 0 0 0 3px rgba(11, 117, 110, 0.08); }
.participant-picker { overflow: hidden; border: 1px solid rgba(19, 54, 58, 0.12); border-radius: 0.65rem; }
.participant-picker-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 0.75rem; border-bottom: 1px solid rgba(19, 54, 58, 0.09); background: #f7faf9; }
.participant-picker-head > div { display: flex; align-items: baseline; gap: 0.6rem; }
.participant-picker-head strong { color: #2b4a4e; font-size: 13px; }
.participant-picker-head span { color: var(--chat-muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.participant-search { display: flex; align-items: center; width: 15rem; height: 2.2rem; gap: 0.45rem; padding: 0 0.65rem; border: 1px solid rgba(19, 54, 58, 0.14); border-radius: 0.45rem; color: #708488; background: #fff; }
.participant-search:focus-within { border-color: rgba(11, 117, 110, 0.5); box-shadow: 0 0 0 3px rgba(11, 117, 110, 0.07); }
.participant-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.45rem; max-height: 20rem; overflow: auto; padding: 0.7rem; }
.participant-option {
  position: relative;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 0.65rem;
  min-height: 3.65rem;
  padding: 0.55rem 0.6rem;
  border: 1px solid rgba(19, 54, 58, 0.1);
  border-radius: 0.55rem;
  background: #fff;
  cursor: pointer;
  transition: border-color 180ms ease, background 180ms ease, transform 180ms ease;
}
.participant-option:hover { border-color: rgba(11, 117, 110, 0.28); background: #f5f9f8; }
.participant-option:active { transform: translateY(1px); }
.participant-option.selected { border-color: rgba(11, 117, 110, 0.42); background: #eaf5f2; }
.participant-option:focus-within { outline: 2px solid rgba(11, 117, 110, 0.3); outline-offset: 1px; }
.participant-option > input { position: absolute; width: 1px; height: 1px; opacity: 0; }
.participant-avatar { display: grid; place-items: center; width: 2.15rem; height: 2.15rem; border-radius: 0.5rem; color: #36575b; background: #e3ece9; font-size: 12px; font-weight: 800; }
.participant-copy { min-width: 0; display: grid; gap: 0.15rem; }
.participant-copy strong,
.participant-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.participant-copy strong { color: #29474b; font-size: 13px; }
.participant-copy small { color: var(--chat-muted); font-size: 12px; }
.participant-check { display: grid; place-items: center; width: 1.25rem; height: 1.25rem; border: 1px solid #b7c7c4; border-radius: 0.35rem; color: transparent; background: #fff; font-size: 12px; font-weight: 850; }
.participant-option.selected .participant-check { border-color: var(--chat-accent); color: #fff; background: var(--chat-accent); }
.participant-loading,
.participant-empty { display: grid; min-height: 8rem; place-items: center; padding: 1rem; color: var(--chat-muted); font-size: 13px; }
.private-chat-error { margin: 0; padding: 0.65rem 0.75rem; border: 1px solid #efd2c6; border-radius: 0.5rem; color: #8b452c; background: #fff7f3; font-size: 12px; }
.private-chat-dialog > footer { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding: 0.9rem 1.35rem; border-top: 1px solid rgba(19, 54, 58, 0.09); background: #fbfcfc; }
.private-chat-dialog > footer > span { color: var(--chat-muted); font-size: 12px; }
.private-chat-dialog > footer > div { display: flex; gap: 0.55rem; }
.private-chat-dialog > footer button { min-height: 2.35rem; padding: 0 1rem; border-radius: 0.45rem; font: inherit; font-size: 13px; font-weight: 750; cursor: pointer; transition: transform 180ms ease, background 180ms ease; }
.private-chat-dialog > footer button:active:not(:disabled) { transform: translateY(1px); }
.private-chat-dialog > footer button:focus-visible { outline: 2px solid rgba(11, 117, 110, 0.35); outline-offset: 2px; }
.dialog-cancel { border: 1px solid rgba(19, 54, 58, 0.14); color: #4e696d; background: #fff; }
.dialog-cancel:hover:not(:disabled) { background: #f1f5f4; }
.dialog-submit { border: 1px solid #0b6964; color: #fff; background: #0b6964; }
.dialog-submit:hover:not(:disabled) { background: #085b58; }

@keyframes chat-shimmer { to { background-position: -200% 0; } }
@keyframes mention-notice-enter {
  from { opacity: 0; transform: translateY(0.35rem); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes mention-attention-pulse {
  0%, 100% {
    border-color: rgba(11, 117, 110, 0.42);
    background: #fff;
    box-shadow: 0 10px 26px rgba(11, 117, 110, 0.1);
    transform: translateX(0) scale(1);
  }
  50% {
    border-color: rgba(11, 117, 110, 0.82);
    background: #dcf4ee;
    box-shadow: 0 0 0 0.35rem rgba(11, 117, 110, 0.14), 0 14px 30px rgba(11, 117, 110, 0.2);
    transform: translateX(0.12rem) scale(1.008);
  }
}

@media (prefers-reduced-motion: reduce) {
  .mention-notice { animation: none; }
  .chat-message.mention-pulse:not(.own) .message-content {
    animation: none;
    border-color: rgba(11, 117, 110, 0.82);
    box-shadow: 0 0 0 0.28rem rgba(11, 117, 110, 0.14), 0 14px 30px rgba(11, 117, 110, 0.16);
  }
}

@media (max-width: 1360px) {
  .project-chat-shell { grid-template-columns: 16rem minmax(30rem, 1fr); }
  .chat-context { display: none; }
}

@media (max-width: 900px) {
  .project-chat-shell { grid-template-columns: minmax(0, 1fr); min-height: 34rem; }
  .channel-rail { display: none; }
  .chat-stage { border-radius: 0.75rem; }
  .chat-message { max-width: 94%; }
  .message-viewport { padding-inline: 1.2rem; }
}

@media (max-width: 620px) {
  .chat-heading { min-height: 4.2rem; padding-inline: 0.8rem; }
  .chat-channel-mark { display: none; }
  .chat-heading h1 { font-size: 16px; }
  .connection-state span { display: none; }
  .connection-state { min-width: 2.2rem; justify-content: center; padding-inline: 0.55rem; }
  .composer-hint { display: none; }
  .mention-menu { right: 0.35rem; left: 0.35rem; width: auto; }
  .message-composer { padding-inline: 0.65rem; }
  .private-chat-dialog { width: min(40rem, calc(100vw - 1rem)); }
  .participant-list { grid-template-columns: minmax(0, 1fr); }
  .participant-picker-head { align-items: stretch; flex-direction: column; }
  .participant-search { width: 100%; }
  .private-chat-dialog > footer { align-items: flex-end; flex-direction: column; }
}
</style>
