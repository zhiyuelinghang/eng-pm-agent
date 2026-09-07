<template>
  <label class="group-file-upload" :class="{ busy, prominent, disabled: disabled || !channelId }"><input type="file" multiple :aria-label="label" :disabled="disabled || busy || !channelId" @change="upload"><n-icon v-if="prominent" :size="16"><Upload /></n-icon><span>{{ busy ? `入库中 ${completed}/${total}…` : label }}</span></label>
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { NIcon, useMessage } from 'naive-ui'
import { Upload } from '@vicons/tabler'
import api, { type ApiEnvelope } from '@/api/client'
import type { ProjectChatMessage } from '@/api/projectChat'
const props = withDefaults(defineProps<{ channelId: number | null; disabled?: boolean; label?: string; prominent?: boolean }>(), { label: '群文件' })
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
.group-file-upload { display: inline-flex; padding: 6px 10px; border-radius: 5px; cursor: pointer; background: #edf4ee; color: #355b48; font-size: 13px; } input { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
.group-file-upload { position: relative; align-items: center; gap: 6px; white-space: nowrap; }
.group-file-upload:focus-within { outline: 2px solid #13968c; outline-offset: 2px; }
.group-file-upload.prominent { padding: 8px 12px; border: 1px solid #08776f; border-radius: 6px; color: white; background: #08776f; line-height: 1.5; font-size: 13px; transition: background .15s, border-color .15s; }
.group-file-upload.prominent:hover:not(.busy):not(.disabled) { background: #09665f; border-color: #09665f; }
.group-file-upload.disabled { opacity: .5; cursor: default; }
 .busy { opacity: .6; cursor: wait; }
</style>
