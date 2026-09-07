import api, { type ApiEnvelope } from '@/api/client'
import type { ProjectChatChannel } from '@/api/projectChat'

export async function checkProjectChatTitle(projectId: string, title: string, excludeChannelId?: number, signal?: AbortSignal) {
  const result = await api.post<ApiEnvelope<{ available: boolean }>>(`/projects/${projectId}/chat/check-title`, {
    title, exclude_channel_id: excludeChannelId,
  }, { signal })
  return result.data.data
}

export type ProjectChatFile = {
  id: number
  knowledge_id: string
  file_name: string
  file_size: number
  parse_status: string | null
  created_at: string | null
}
export async function addProjectChatMembers(channelId: number, userIds: number[]) {
  const result = await api.post<ApiEnvelope<ProjectChatChannel>>(`/chat/channels/${channelId}/members`, { user_ids: userIds })
  return result.data.data
}
export async function transferProjectChatOwner(channelId: number, userId: number) {
  const result = await api.post<ApiEnvelope<ProjectChatChannel>>(`/chat/channels/${channelId}/owner`, { user_id: userId })
  return result.data.data
}
export async function updateProjectChatSettings(channelId: number, title: string) {
  const result = await api.patch<ApiEnvelope<ProjectChatChannel>>(`/chat/channels/${channelId}/settings`, { title })
  return result.data.data
}
export async function listProjectChatFiles(channelId: number, beforeId?: number, signal?: AbortSignal) {
  const result = await api.get<ApiEnvelope<{ items: ProjectChatFile[]; next_cursor: number | null }>>(`/chat/channels/${channelId}/files`, {
    params: { before_id: beforeId, limit: 50 }, signal,
  })
  return result.data.data
}

export async function removeProjectChatMember(channelId: number, userId: number) {
  const result = await api.delete<ApiEnvelope<ProjectChatChannel>>(`/chat/channels/${channelId}/members/${userId}`)
  return result.data.data
}

export async function saveProjectChatMembership(channelId: number, userIds: number[], autoSync: boolean, ownerUserId: number) {
  const result = await api.put<ApiEnvelope<ProjectChatChannel>>(`/chat/channels/${channelId}/members`, { user_ids: userIds, auto_sync: autoSync, owner_user_id: ownerUserId })
  return result.data.data
}
