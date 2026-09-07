<template>
  <div v-if="files.length" class="group-message-files" aria-label="群文件"><button v-for="file in files" :key="file.knowledge_id" type="button" :disabled="Boolean(downloading)" @click="download(file)">{{ downloading === file.knowledge_id ? '下载中…' : file.file_name }}<small>已入知识库 · {{ file.folder_path }}</small></button></div>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMessage } from 'naive-ui'
import api from '@/api/client'
import type { ProjectChatMessage } from '@/api/projectChat'
const props = defineProps<{ message: ProjectChatMessage; projectId: string }>()
const notice = useMessage(), downloading = ref('')
type GroupFile = { knowledge_id: string; file_name: string; folder_path: string }
const files = computed<GroupFile[]>(() => {
  const values = props.message.metadata?.attachments
  return Array.isArray(values) ? values.filter(file => file && typeof file.knowledge_id === 'string' && typeof file.file_name === 'string') : []
})
async function download(file: GroupFile) {
  if (downloading.value) return
  downloading.value = file.knowledge_id
  try {
    const result = await api.get(`/projects/${props.projectId}/engineering-documents/knowledge/${encodeURIComponent(file.knowledge_id)}/download`, { responseType: 'blob' })
    const url = URL.createObjectURL(result.data), link = document.createElement('a')
    link.href = url; link.download = file.file_name; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch { notice.error('文件下载失败，请确认文件仍存在且具有访问权限。') }
  finally { downloading.value = '' }
}
</script>
<style scoped>
button { display: grid; gap: 5px; padding: 12px; margin-top: 8px; border: 1px solid #c7dcd1; border-radius: 6px; background: #f1f7f3; color: #234f3c; font: inherit; font-size: 14px; text-align: left; cursor: pointer; overflow-wrap: anywhere; } small { font-size: 12px; color: #617c6d; }
</style>
