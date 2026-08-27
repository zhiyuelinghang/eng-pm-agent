import { Centrifuge } from 'centrifuge'

import api, { type ApiEnvelope } from '@/api/client'

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
  task_ids: number[]
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
  member_role: 'owner' | 'member'
  muted: boolean
}

export type ProjectChatParticipant = {
  user_id: number
  name: string
  title: string
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

export type ProjectChatRealtimeStatus =
  | 'connecting'
  | 'connected'
  | 'polling'
  | 'disconnected'

type RealtimeToken = {
  enabled: boolean
  ws_url: string
  token: string | null
  channels: string[]
}

type ProjectChatEvent =
  | {
      type: 'chat.message.created'
      project_id: number
      channel_id: number
      message: ProjectChatMessage
    }
  | {
      type: 'chat.channel.created'
      project_id: number
      channel_id: number
    }
  | {
      type: 'chat.mention.created'
      project_id: number
      channel_id: number
      message: ProjectChatMessage
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
  const { task_assistant: taskAssistant, business_agents: businessAgents } = response.data.data
  return [taskAssistant, ...businessAgents]
    .filter((agent): agent is ProjectChatAgent => Boolean(agent))
    .filter((agent, index, agents) => agents.findIndex(item => item.id === agent.id) === index)
}

export async function createPrivateProjectChatChannel(
  projectId: string,
  payload: { title?: string; participant_user_ids: number[] },
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

async function getRealtimeToken(projectId: string) {
  const response = await api.get<ApiEnvelope<RealtimeToken>>(
    `/projects/${projectId}/chat/realtime-token`,
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

export async function connectProjectChatRealtime(
  projectId: string,
  callbacks: {
    onMessage: (message: ProjectChatMessage) => void
    onStatus: (status: ProjectChatRealtimeStatus) => void
    onChannelsChanged?: () => void
    onMention?: (message: ProjectChatMessage) => void
  },
) {
  const initial = await getRealtimeToken(projectId)
  if (!initial.enabled || !initial.token) {
    callbacks.onStatus('polling')
    return null
  }

  callbacks.onStatus('connecting')
  const client = new Centrifuge(browserWebSocketUrl(initial.ws_url), {
    token: initial.token,
    getToken: async () => {
      const refreshed = await getRealtimeToken(projectId)
      if (!refreshed.enabled || !refreshed.token) {
        throw new Error('项目群聊实时连接已停用')
      }
      return refreshed.token
    },
  })

  client.on('connected', () => callbacks.onStatus('connected'))
  client.on('connecting', () => callbacks.onStatus('connecting'))
  client.on('disconnected', () => callbacks.onStatus('disconnected'))
  client.on('publication', context => {
    const event = context.data as ProjectChatEvent | undefined
    if (!event || event.project_id !== Number(projectId)) return
    if (event.type === 'chat.message.created') {
      callbacks.onMessage(event.message)
    } else if (event.type === 'chat.channel.created') {
      callbacks.onChannelsChanged?.()
    } else if (event.type === 'chat.mention.created') {
      callbacks.onMention?.(event.message)
    }
  })
  client.connect()
  return client
}
