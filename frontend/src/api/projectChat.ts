import { Centrifuge, type Subscription } from 'centrifuge'

import api, { type ApiEnvelope } from '@/api/client'
import {
  registerRealtimeSessionCleanup,
  registerRealtimeSessionProject,
} from '@/services/realtimeSession'

export type ChatSender = {
  id: number
  name: string
  title: string
  system_role: string
}

export type ProjectChatMessage = {
  id: number
  channel_id: number
  sender_type: 'user' | 'agent' | 'system'
  sender_user_id: number | null
  sender_agent_id: string | null
  sender: ChatSender | null
  message_type: 'text' | 'agent' | 'system' | 'task_draft' | 'task_event'
  content: string
  client_message_id: string | null
  reply_to_id: number | null
  task_ids: string[]
  metadata: Record<string, unknown>
  mentions: Array<{
    target_type: 'all' | 'user' | 'agent'
    target_user_id: number | null
    target_agent_id: string | null
    display_name: string
  }>
  created_at: string | null
  updated_at: string | null
  edited_at: string | null
  deleted_at: string | null
}

export type ProjectChatChannel = {
  id: number
  project_id: number
  created_by_user_id: number | null
  title: string
  summary: string
  channel_type: 'project' | 'topic' | 'private'
  all_members?: boolean
  member_count: number
  last_message: ProjectChatMessage | null
  last_message_at: string | null
  created_at: string | null
  updated_at: string | null
}

export type ProjectChatMember = {
  id: number
  user_id: number
  name: string
  title: string
  positions?: string[]
  member_role: 'owner' | 'member'
  muted: boolean
}

export type ProjectChatParticipant = {
  user_id: number
  name: string
  title: string
  positions?: string[]
}

export type ProjectChatAgent = {
  id: string
  name: string
  description: string | null
  category: string | null
  role: string
  enabled: boolean
  published: boolean
  model_ready: boolean
  sort_order: number
}

export type ProjectChatTaskDraftStep = {
  name: string
  node_type: 'manual' | 'project_chat_message'
  owner_user_id?: number | null
  due_at?: string | null
  material?: string | null
  action?: {
    type: 'project_chat_message'
    channel_id: number
    sender_agent_id?: string
    sender_agent_name?: string
    mention_mode: 'none' | 'all' | 'users'
    mentioned_user_ids: number[]
    content: string
  }
}

export type ProjectChatTaskDraft = {
  title: string
  task_type: string
  action_type: 'responsibility_task' | 'project_chat_message'
  risk_level: 'critical' | 'high' | 'medium' | 'low'
  assignee_user_id?: number | null
  confirmer_user_id?: number | null
  wbs_item_id?: number | null
  risk_source_id?: number | null
  trigger_reason?: string | null
  required_materials: string[]
  workflow_steps: ProjectChatTaskDraftStep[]
  run_mode: 'immediate' | 'once' | 'recurring' | 'calendar'
  trigger_date?: string | null
  trigger_time: string
  trigger_interval_value: number
  trigger_interval_unit: 'minute' | 'hour' | 'day' | 'week' | 'month'
  trigger_end_mode: 'never' | 'until' | 'count'
  cc?: string | null
  target_channel_id?: number | null
  mention_mode: 'none' | 'all' | 'users'
  mentioned_user_ids: number[]
  message_content?: string | null
  generated_by?: string | null
  generation_note?: string | null
  trigger_rule?: string | null
}

export type ProjectChatTaskDraftPublishResult = {
  message: ProjectChatMessage
  result: Record<string, unknown>
}

export type ProjectChatPrivateTaskDraftStatus =
  | 'generating'
  | 'ready'
  | 'publishing'
  | 'published'
  | 'dismissed'
  | 'cancelled'
  | 'failed'

export type ProjectChatPrivateTaskDraft = {
  id: number
  project_id: number
  channel_id: number
  channel_title: string
  requested_by_user_id: number
  request_text: string
  status: ProjectChatPrivateTaskDraftStatus
  draft: ProjectChatTaskDraft | null
  error: string | null
  publish_result: Record<string, unknown> | null
  published_task_ids: string[]
  published_message_id: number | null
  created_at: string | null
  updated_at: string | null
}

export type ProjectChatPrivateTaskDraftPublishResult = {
  draft: ProjectChatPrivateTaskDraft
  message: ProjectChatMessage | null
  result: Record<string, unknown>
}

export type ProjectChatRealtimeStatus =
  | 'connecting'
  | 'connected'
  | 'polling'
  | 'disconnected'

type RealtimeConnectionToken = {
  enabled: boolean
  ws_url: string
  token: string | null
}

type RealtimeSubscriptionAccess = {
  channel: string
  token: string | null
}

type RealtimeProjectAccess = {
  enabled: boolean
  project_id: number
  subscriptions: RealtimeSubscriptionAccess[]
}

type RealtimeSubscriptionToken = {
  enabled: boolean
  channel: string
  token: string | null
}

type ProjectChatEvent =
  | {
      type: 'chat.message.created'
      project_id: number
      channel_id: number
      message: ProjectChatMessage
    }
  | {
      type: 'chat.channel.created' | 'chat.channel.updated'
      project_id: number
      channel_id: number
    }
  | {
      type: 'chat.mention.created'
      project_id: number
      channel_id: number
      message: ProjectChatMessage
    }
  | {
      type: 'chat.task_draft.updated'
      project_id: number
      channel_id: number
      draft: ProjectChatPrivateTaskDraft
    }

export async function listProjectChatChannels(projectId: string) {
  const response = await api.get<ApiEnvelope<ProjectChatChannel[]>>(
    `/projects/${projectId}/chat/channels`,
  )
  return response.data.data
}

export async function listProjectChatParticipants(projectId: string) {
  const response = await api.get<ApiEnvelope<ProjectChatParticipant[]>>(
    `/projects/${projectId}/chat/participants`,
  )
  return response.data.data
}

export async function listProjectChatAgents() {
  const response = await api.get<ApiEnvelope<{
    task_assistant: ProjectChatAgent | null
    business_agents: ProjectChatAgent[]
  }>>('/agents/catalog')
  const {
    task_assistant: taskAssistant,
    business_agents: businessAgents,
  } = response.data.data
  return [taskAssistant, ...businessAgents]
    .filter((agent): agent is ProjectChatAgent => Boolean(agent))
    .filter((agent, index, agents) => agents.findIndex(item => item.id === agent.id) === index)
}

export async function createPrivateProjectChatChannel(
  projectId: string,
  payload: { title: string; participant_user_ids: number[]; all_members?: boolean },
) {
  const response = await api.post<ApiEnvelope<ProjectChatChannel>>(
    `/projects/${projectId}/chat/channels`,
    payload,
  )
  return response.data.data
}

export async function listProjectChatMembers(channelId: number) {
  const response = await api.get<ApiEnvelope<ProjectChatMember[]>>(
    `/chat/channels/${channelId}/members`,
  )
  return response.data.data
}

export async function listProjectChatMessages(
  channelId: number,
  options: { afterId?: number; limit?: number } = {},
) {
  const response = await api.get<ApiEnvelope<ProjectChatMessage[]>>(
    `/chat/channels/${channelId}/messages`,
    {
      params: {
        after_id: options.afterId,
        limit: options.limit ?? 100,
      },
    },
  )
  return response.data.data
}

export async function listProjectChatMentionNotices(projectId: string) {
  const response = await api.get<ApiEnvelope<ProjectChatMessage[]>>(
    `/projects/${projectId}/chat/mention-notices`,
  )
  return response.data.data
}

export async function getProjectChatMessage(messageId: number) {
  const response = await api.get<ApiEnvelope<ProjectChatMessage>>(
    `/chat/messages/${messageId}`,
  )
  return response.data.data
}

export async function sendProjectChatMessage(
  channelId: number,
  content: string,
  mentions: {
    mentionAll?: boolean
    mentionedUserIds?: number[]
    mentionedAgentIds?: string[]
  } = {},
) {
  const response = await api.post<ApiEnvelope<ProjectChatMessage>>(
    `/chat/channels/${channelId}/messages`,
    {
      content,
      client_message_id: crypto.randomUUID(),
      mention_all: mentions.mentionAll ?? false,
      mentioned_user_ids: mentions.mentionedUserIds ?? [],
      mentioned_agent_ids: mentions.mentionedAgentIds ?? [],
    },
  )
  return response.data.data
}

export async function claimProjectChatMention(messageId: number) {
  const response = await api.post<ApiEnvelope<{ first_seen: boolean }>>(
    `/chat/messages/${messageId}/mention-seen`,
  )
  return response.data.data
}

export async function publishProjectChatTaskDraft(
  messageId: number,
  payload: ProjectChatTaskDraft,
) {
  const response = await api.post<ApiEnvelope<ProjectChatTaskDraftPublishResult>>(
    `/chat/messages/${messageId}/task-draft/publish`,
    payload,
  )
  return response.data
}

export async function dismissProjectChatTaskDraft(messageId: number) {
  const response = await api.post<ApiEnvelope<ProjectChatMessage>>(
    `/chat/messages/${messageId}/task-draft/dismiss`,
  )
  return response.data.data
}

export async function createProjectChatTaskDraft(
  channelId: number,
  requirement: string,
) {
  const response = await api.post<ApiEnvelope<ProjectChatPrivateTaskDraft>>(
    `/chat/channels/${channelId}/task-drafts`,
    {
      requirement,
      client_request_id: crypto.randomUUID(),
    },
  )
  return response.data.data
}

export async function createHomeAgentTaskDraft(
  projectId: string,
  conversationId: number | null,
  requirement: string,
) {
  const response = await api.post<ApiEnvelope<ProjectChatPrivateTaskDraft>>(
    `/projects/${projectId}/agent-task-drafts`,
    {
      requirement,
      conversation_id: conversationId,
      client_request_id: crypto.randomUUID(),
    },
  )
  return response.data.data
}

export async function listProjectChatTaskDrafts(projectId: string) {
  const response = await api.get<ApiEnvelope<ProjectChatPrivateTaskDraft[]>>(
    `/projects/${projectId}/chat/task-drafts`,
    { params: { active_only: true } },
  )
  return response.data.data
}

export async function getProjectChatTaskDraft(draftId: number) {
  const response = await api.get<ApiEnvelope<ProjectChatPrivateTaskDraft>>(
    `/chat/task-drafts/${draftId}`,
  )
  return response.data.data
}

export async function publishPrivateProjectChatTaskDraft(
  draftId: number,
  payload: ProjectChatTaskDraft,
) {
  const response = await api.post<
    ApiEnvelope<ProjectChatPrivateTaskDraftPublishResult>
  >(`/chat/task-drafts/${draftId}/publish`, payload)
  return response.data
}

export async function dismissPrivateProjectChatTaskDraft(draftId: number) {
  const response = await api.post<ApiEnvelope<ProjectChatPrivateTaskDraft>>(
    `/chat/task-drafts/${draftId}/dismiss`,
  )
  return response.data.data
}

export async function retryPrivateProjectChatTaskDraft(draftId: number) {
  const response = await api.post<ApiEnvelope<ProjectChatPrivateTaskDraft>>(
    `/chat/task-drafts/${draftId}/retry`,
  )
  return response.data.data
}

export async function stopPrivateProjectChatTaskDraft(draftId: number) {
  const response = await api.post<ApiEnvelope<ProjectChatPrivateTaskDraft>>(
    `/chat/task-drafts/${draftId}/stop`,
  )
  return response.data.data
}

export async function retryProjectChatTaskDraft(messageId: number) {
  const response = await api.post<ApiEnvelope<ProjectChatMessage>>(
    `/chat/messages/${messageId}/task-draft/retry`,
  )
  return response.data.data
}

export async function stopProjectChatTaskDraft(messageId: number) {
  const response = await api.post<ApiEnvelope<ProjectChatMessage>>(
    `/chat/messages/${messageId}/task-draft/stop`,
  )
  return response.data.data
}

export async function stopProjectChatAgentRun(messageId: number) {
  const response = await api.post<ApiEnvelope<ProjectChatMessage>>(`/chat/messages/${messageId}/agent/stop`)
  return response.data.data
}

export async function confirmProjectChatAgentTool(messageId: number, payload: {
  reply_id: string; tool_call: Record<string, unknown>; confirmed: boolean
}) {
  const response = await api.post<ApiEnvelope<ProjectChatMessage>>(`/chat/messages/${messageId}/agent/confirm`, payload)
  return response.data.data
}

async function getRealtimeConnectionToken() {
  const response = await api.get<ApiEnvelope<RealtimeConnectionToken>>(
    '/chat/realtime-token',
  )
  return response.data.data
}

async function getRealtimeProjectAccess(projectId: string) {
  const response = await api.get<ApiEnvelope<RealtimeProjectAccess>>(
    `/projects/${projectId}/chat/realtime-subscriptions`,
  )
  return response.data.data
}

async function refreshRealtimeSubscriptionToken(projectId: string, channel: string) {
  const response = await api.get<ApiEnvelope<RealtimeSubscriptionToken>>(
    `/projects/${projectId}/chat/realtime-subscription-token`,
    { params: { channel } },
  )
  return response.data.data
}

function browserWebSocketUrl(configuredUrl: string) {
  const url = new URL(configuredUrl, window.location.href)
  const configuredForLocalhost = url.hostname === '127.0.0.1' || url.hostname === 'localhost'
  const openedFromAnotherHost = window.location.hostname !== '127.0.0.1'
    && window.location.hostname !== 'localhost'
  if (configuredForLocalhost && openedFromAnotherHost) {
    url.hostname = window.location.hostname
  }
  if (window.location.protocol === 'https:') url.protocol = 'wss:'
  return url.toString()
}

type ProjectChatRealtimeCallbacks = {
  onMessage: (message: ProjectChatMessage) => void
  onStatus: (status: ProjectChatRealtimeStatus) => void
  onChannelsChanged?: () => void
  onMention?: (message: ProjectChatMessage) => void
  onTaskDraft?: (draft: ProjectChatPrivateTaskDraft) => void
}

type ProjectChatRealtimeHub = {
  client: Centrifuge | null
  started: boolean
  startPromise: Promise<void> | null
  transportStatus: ProjectChatRealtimeStatus
  projectId: string
  projectStatus: 'idle' | 'loading' | 'ready' | 'error'
  projectGeneration: number
  projectSyncPromise: Promise<void> | null
  status: ProjectChatRealtimeStatus
  channelSubscriptions: Map<string, Subscription>
  subscribers: Set<ProjectChatRealtimeCallbacks>
}

let activeRealtimeHub: ProjectChatRealtimeHub | null = null
let desiredRealtimeProjectId = ''
let realtimeSessionRetryTimer: number | null = null

function clearRealtimeSessionRetry() {
  if (realtimeSessionRetryTimer !== null) {
    window.clearTimeout(realtimeSessionRetryTimer)
  }
  realtimeSessionRetryTimer = null
}

function effectiveRealtimeStatus(hub: ProjectChatRealtimeHub): ProjectChatRealtimeStatus {
  if (hub.transportStatus !== 'connected') return hub.transportStatus
  if (!hub.projectId || hub.projectStatus === 'ready') return 'connected'
  if (hub.projectStatus === 'error') return 'polling'
  return 'connecting'
}

function broadcastRealtimeStatus(hub: ProjectChatRealtimeHub) {
  if (activeRealtimeHub !== hub) return
  const status = effectiveRealtimeStatus(hub)
  hub.status = status
  hub.subscribers.forEach(subscriber => subscriber.onStatus(status))
}

function broadcastRealtimeEvent(hub: ProjectChatRealtimeHub, event: ProjectChatEvent) {
  if (activeRealtimeHub !== hub || event.project_id !== Number(hub.projectId)) return
  if ((event.type === 'chat.channel.created' || event.type === 'chat.channel.updated')) {
    void syncRealtimeProject(hub, hub.projectId, true).catch(() => undefined)
  }
  hub.subscribers.forEach(subscriber => {
    if (event.type === 'chat.message.created') {
      subscriber.onMessage(event.message)
    } else if ((event.type === 'chat.channel.created' || event.type === 'chat.channel.updated')) {
      subscriber.onChannelsChanged?.()
    } else if (event.type === 'chat.mention.created') {
      subscriber.onMention?.(event.message)
    } else if (event.type === 'chat.task_draft.updated') {
      subscriber.onTaskDraft?.(event.draft)
    }
  })
}

function createRealtimeHub(): ProjectChatRealtimeHub {
  return {
    client: null,
    started: false,
    startPromise: null,
    transportStatus: 'connecting',
    projectId: '',
    projectStatus: 'idle',
    projectGeneration: 0,
    projectSyncPromise: null,
    status: 'connecting',
    channelSubscriptions: new Map(),
    subscribers: new Set(),
  }
}

function clearRealtimeProjectSubscriptions(hub: ProjectChatRealtimeHub) {
  hub.channelSubscriptions.forEach(subscription => {
    subscription.unsubscribe()
    hub.client?.removeSubscription(subscription)
  })
  hub.channelSubscriptions.clear()
}

function installRealtimeProjectSubscriptions(
  hub: ProjectChatRealtimeHub,
  projectId: string,
  subscriptions: RealtimeSubscriptionAccess[],
) {
  const client = hub.client
  if (!client) throw new Error('实时连接尚未初始化')
  const nextChannels = new Set(subscriptions.map(item => item.channel))
  hub.channelSubscriptions.forEach((subscription, channel) => {
    if (nextChannels.has(channel)) return
    subscription.unsubscribe()
    client.removeSubscription(subscription)
    hub.channelSubscriptions.delete(channel)
  })

  subscriptions.forEach(access => {
    if (hub.channelSubscriptions.has(access.channel)) return
    if (!access.token) throw new Error('项目群聊订阅令牌缺失')
    const subscription = client.newSubscription(access.channel, {
      token: access.token,
      getToken: async context => {
        const refreshed = await refreshRealtimeSubscriptionToken(
          projectId,
          context.channel,
        )
        if (!refreshed.enabled || !refreshed.token) {
          throw new Error('项目群聊实时订阅已停用')
        }
        return refreshed.token
      },
    })
    subscription.on('publication', context => {
      const event = context.data as ProjectChatEvent | undefined
      if (event) broadcastRealtimeEvent(hub, event)
    })
    subscription.on('unsubscribed', context => {
      if (
        activeRealtimeHub === hub
        && hub.projectId === projectId
        && context.code !== 0
      ) {
        hub.projectStatus = 'error'
        broadcastRealtimeStatus(hub)
      }
    })
    hub.channelSubscriptions.set(access.channel, subscription)
    subscription.subscribe()
  })
}

async function syncRealtimeProject(
  hub: ProjectChatRealtimeHub,
  projectId: string,
  force = false,
) {
  if (activeRealtimeHub !== hub) return
  if (
    hub.projectId === projectId
    && hub.projectSyncPromise
    && !force
  ) {
    await hub.projectSyncPromise
    return
  }
  if (
    hub.projectId === projectId
    && hub.projectStatus === 'ready'
    && !force
  ) return

  const projectChanged = hub.projectId !== projectId
  if (projectChanged) {
    hub.projectId = projectId
    clearRealtimeProjectSubscriptions(hub)
  }
  const generation = ++hub.projectGeneration
  if (!projectId) {
    hub.projectStatus = 'idle'
    hub.projectSyncPromise = null
    broadcastRealtimeStatus(hub)
    return
  }
  if (hub.transportStatus === 'polling') {
    hub.projectStatus = 'error'
    broadcastRealtimeStatus(hub)
    return
  }

  hub.projectStatus = 'loading'
  broadcastRealtimeStatus(hub)
  const syncPromise = (async () => {
    const access = await getRealtimeProjectAccess(projectId)
    if (
      activeRealtimeHub !== hub
      || hub.projectId !== projectId
      || hub.projectGeneration !== generation
    ) return
    if (!access.enabled) throw new Error('项目群聊实时订阅已停用')
    installRealtimeProjectSubscriptions(hub, projectId, access.subscriptions)
    hub.projectStatus = 'ready'
    broadcastRealtimeStatus(hub)
  })()
  hub.projectSyncPromise = syncPromise
  try {
    await syncPromise
  } catch (error) {
    if (
      activeRealtimeHub === hub
      && hub.projectId === projectId
      && hub.projectGeneration === generation
    ) {
      hub.projectStatus = 'error'
      broadcastRealtimeStatus(hub)
    }
    throw error
  } finally {
    if (hub.projectSyncPromise === syncPromise) hub.projectSyncPromise = null
  }
}

async function startRealtimeHub(hub: ProjectChatRealtimeHub) {
  if (hub.started) {
    if (hub.startPromise) await hub.startPromise
    return
  }

  hub.started = true
  hub.startPromise = (async () => {
    const initial = await getRealtimeConnectionToken()
    if (activeRealtimeHub !== hub) return
    if (!initial.enabled || !initial.token) {
      hub.transportStatus = 'polling'
      broadcastRealtimeStatus(hub)
      return
    }

    const client = new Centrifuge(browserWebSocketUrl(initial.ws_url), {
      token: initial.token,
      getToken: async () => {
        const refreshed = await getRealtimeConnectionToken()
        if (!refreshed.enabled || !refreshed.token) {
          throw new Error('项目群聊实时连接已停用')
        }
        return refreshed.token
      },
    })
    hub.client = client
    client.on('connected', () => {
      hub.transportStatus = 'connected'
      broadcastRealtimeStatus(hub)
    })
    client.on('connecting', () => {
      hub.transportStatus = 'connecting'
      broadcastRealtimeStatus(hub)
    })
    client.on('disconnected', () => {
      hub.transportStatus = 'disconnected'
      broadcastRealtimeStatus(hub)
    })
    client.connect()
  })()

  try {
    await hub.startPromise
  } catch (error) {
    hub.started = false
    throw error
  } finally {
    hub.startPromise = null
  }
}

export async function startProjectChatRealtimeSession(projectId = '') {
  if (!activeRealtimeHub) activeRealtimeHub = createRealtimeHub()
  const hub = activeRealtimeHub
  await startRealtimeHub(hub)
  await syncRealtimeProject(hub, projectId)
}

export async function connectProjectChatRealtime(
  projectId: string,
  callbacks: ProjectChatRealtimeCallbacks,
) {
  if (!activeRealtimeHub) activeRealtimeHub = createRealtimeHub()
  const hub = activeRealtimeHub
  hub.subscribers.add(callbacks)
  callbacks.onStatus(hub.status)
  try {
    await startProjectChatRealtimeSession(projectId)
  } catch (error) {
    hub.subscribers.delete(callbacks)
    throw error
  }

  let subscribed = true
  return {
    disconnect() {
      if (!subscribed) return
      subscribed = false
      hub.subscribers.delete(callbacks)
    },
  }
}

export function disconnectProjectChatRealtime() {
  desiredRealtimeProjectId = ''
  clearRealtimeSessionRetry()
  const hub = activeRealtimeHub
  activeRealtimeHub = null
  if (!hub) return
  hub.subscribers.clear()
  hub.projectGeneration += 1
  clearRealtimeProjectSubscriptions(hub)
  hub.client?.disconnect()
  hub.client = null
  hub.started = false
  hub.startPromise = null
  hub.projectSyncPromise = null
}

const unregisterRealtimeSessionCleanup = registerRealtimeSessionCleanup(
  disconnectProjectChatRealtime,
)

function maintainProjectChatRealtimeSession(projectId: string) {
  desiredRealtimeProjectId = projectId
  clearRealtimeSessionRetry()
  void startProjectChatRealtimeSession(projectId).catch(() => {
    if (
      desiredRealtimeProjectId !== projectId
      || !sessionStorage.getItem('access_token')
    ) return
    realtimeSessionRetryTimer = window.setTimeout(
      () => maintainProjectChatRealtimeSession(projectId),
      5000,
    )
  })
}

const unregisterRealtimeSessionProject = registerRealtimeSessionProject(
  maintainProjectChatRealtimeSession,
)

if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    unregisterRealtimeSessionCleanup()
    unregisterRealtimeSessionProject()
    disconnectProjectChatRealtime()
  })
}
