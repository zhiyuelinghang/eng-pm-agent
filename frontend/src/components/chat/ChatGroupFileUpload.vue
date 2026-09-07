<template>
  <label class="group-file-upload" :class="{ busy }"><input type="file" multiple :disabled="disabled || busy || !channelId" @change="upload"><span>{{ busy ? `入库中 ${completed}/${total}…` : '群文件' }}</span></label>
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { useMessage } from 'naive-ui'
import api, { type ApiEnvelope } from '@/api/client'
import type { ProjectChatMessage } from '@/api/projectChat'
const props = defineProps<{ channelId: number | null; disabled?: boolean }>()
const emit = defineEmits<{ uploaded: [message: ProjectChatMessage] }>()
const notice = useMessage(), busy = ref(false), completed = ref(0), total = ref(0)
let disposed = false
let uploadController: AbortController | null = null
onBeforeUnmount(() => { disposed = true; uploadController?.abort() })
async function upload(event: Event) {
  const input = event.target as HTMLInputElement, files = [...(input.files || [])], channelId = props.channelId
  input.value = ''
  if (busy.value || !channelId || !files.length) return
  if (files.some(file => file.size > 50 * 1024 * 1024 || !file.size)) { notice.warning('请选择非空文件，每个文件不超过 50 MB。'); return }
  busy.value = true; completed.value = 0; total.value = files.length
  const sessionToken = sessionStorage.getItem('access_token')
  uploadController = new AbortController()
  try {
    for (const file of files) {
      if (disposed || sessionStorage.getItem('access_token') !== sessionToken) return
      const data = new FormData(); data.append('file', file); data.append('client_message_id', crypto.randomUUID())
      const result = await api.post<ApiEnvelope<ProjectChatMessage>>(`/chat/channels/${channelId}/files`, data, { timeout: 180000, signal: uploadController.signal })
      if (disposed || sessionStorage.getItem('access_token') !== sessionToken) return
      completed.value++; emit('uploaded', result.data.data)
    }
    notice.success('群文件已自动入库，按群名称存储；仅群成员与工程管理员可见。')
  } catch (error: any) { if (!disposed) notice.error(error.response?.data?.detail || `入库失败，已成功 ${completed.value} 个，请重试剩余文件。`) }
  finally { busy.value = false; uploadController = null }
}
</script>
<style scoped>
.group-file-upload { display: inline-flex; padding: 6px 10px; border-radius: 5px; cursor: pointer; background: #edf4ee; color: #355b48; font-size: 13px; } input { display: none; } .busy { opacity: .6; cursor: wait; }
</style>
