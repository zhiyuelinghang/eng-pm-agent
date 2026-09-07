import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import api, { type ApiEnvelope } from '@/api/client'

export const useChatUnreadStore = defineStore('chatUnread', () => {
  const projectId = ref(''), counts = ref<Record<string, number>>({})
  const total = computed(() => Object.values(counts.value).reduce((sum, count) => sum + count, 0))
  const taskCounts = ref<{ tasks: number; home_todo: number } | null>(null)
  let taskGeneration = 0
  let generation = 0
  function reset(id = '') { generation++; taskGeneration++; projectId.value = id; counts.value = {}; taskCounts.value = null }
  async function refreshTasks(id = projectId.value) {
    if (!id || id !== projectId.value) return
    const version = ++taskGeneration
    try {
      const result = await api.get<ApiEnvelope<{ tasks: number; home_todo: number }>>(`/projects/${id}/my-task-counts`)
      if (version === taskGeneration && id === projectId.value) taskCounts.value = result.data.data
    } catch { /* 断网时保留已确认的任务数量。 */ }
  }
  async function refresh(id = projectId.value) {
    if (id !== projectId.value) reset(id)
    if (!id) return
    const version = ++generation
    try {
      const result = await api.get<ApiEnvelope<{ total: number; channels: Record<string, number> }>>(`/projects/${id}/chat/unread`)
      if (version === generation && projectId.value === id) counts.value = result.data.data.channels
    } catch { /* 短暂断网保留上次已确认的计数，下次刷新重试。 */ }
  }
  async function markRead(id: string, channelId: number, messageId: number) {
    await api.post(`/chat/channels/${channelId}/read`, { message_id: messageId })
    if (projectId.value === id) await refresh(id)
  }
  return { counts, total, projectId, taskCounts, reset, refresh, refreshTasks, markRead }
})
