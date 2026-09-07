<template>
  <section class="announcement-panel" aria-label="项目公告">
    <header><div><h2>项目公告</h2><p>由工程管理员发布，当前项目成员可查看。</p></div><button v-if="isAdmin" :disabled="busy" @click="editing = !editing">{{ editing ? '取消发布' : '发布公告' }}</button></header>
    <form v-if="editing" @submit.prevent="publish"><label>公告标题<input v-model.trim="draft.title" required maxlength="200" :disabled="busy"></label><label>公告内容<textarea v-model.trim="draft.content" required maxlength="20000" rows="5" :disabled="busy"></textarea></label><button :disabled="busy">{{ busy ? '发布中…' : '发布到当前项目' }}</button></form>
    <p v-if="loading" role="status">正在加载公告…</p><p v-else-if="error" role="alert">{{ error }} <button @click="load">重试</button></p>
    <p v-else-if="!items.length" class="empty">当前项目暂无公告。</p>
    <article v-for="item in items" :key="item.id"><header><div><h3>{{ item.title }}</h3><span>{{ item.author_name }} · {{ formatTime(item.created_at) }}</span></div><button v-if="isAdmin" :disabled="busy" @click="withdraw(item.id)">撤回</button></header><p class="content">{{ item.content }}</p></article>
  </section>
</template>
<script setup lang="ts">
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useMessage } from 'naive-ui'
import api, { type ApiEnvelope } from '@/api/client'
type Announcement = { id: number; title: string; content: string; author_name: string; created_at: string }
const props = defineProps<{ projectId: string }>()
const emit = defineEmits<{ count: [value: number] }>()
const isAdmin = sessionStorage.getItem('user_role') === 'admin'
const message = useMessage(), items = ref<Announcement[]>([]), loading = ref(false), error = ref(''), busy = ref(false), editing = ref(false)
const draft = reactive({ title: '', content: '' })
let generation = 0
function formatTime(value: string) { return new Date(value).toLocaleString('zh-CN', { hour12: false }) }
async function load() {
  const version = ++generation, projectId = props.projectId
  if (!projectId) { items.value = []; emit('count', 0); return }
  loading.value = true; error.value = ''
  try { const result = await api.get<ApiEnvelope<Announcement[]>>(`/projects/${projectId}/announcements`); if (version === generation) { items.value = result.data.data; emit('count', items.value.length) } }
  catch (err: any) { if (version === generation) error.value = err.response?.data?.detail || '公告加载失败' }
  finally { if (version === generation) loading.value = false }
}
async function publish() {
  if (busy.value) return
  busy.value = true
  const projectId = props.projectId
  try { await api.post(`/projects/${projectId}/announcements`, { ...draft }); if (projectId === props.projectId) { Object.assign(draft, { title: '', content: '' }); editing.value = false; message.success('公告已发布'); await load() } }
  catch (err: any) { message.error(err.response?.data?.detail || '公告发布失败') }
  finally { busy.value = false }
}
async function withdraw(id: number) {
  if (busy.value) return
  busy.value = true
  try { await api.delete(`/projects/${props.projectId}/announcements/${id}`); message.success('公告已撤回'); await load() }
  catch (err: any) { message.error(err.response?.data?.detail || '公告撤回失败') }
  finally { busy.value = false }
}
watch(() => props.projectId, () => { items.value = []; editing.value = false; Object.assign(draft, { title: '', content: '' }); void load() }, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>
<style scoped>
.announcement-panel { padding: 24px; overflow: auto; min-height: 0; background: white; border-radius: 10px; color: #163d34; font-size: 14px; } header { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; } h2 { font-size: 21px; margin: 0; } h3 { font-size: 17px; margin: 0 0 8px; } header p, header span { color: #718079; font-size: 13px; } button, input, textarea { font: inherit; } button { background: #ecf4ef; color: #235a41; border: 1px solid #c8dace; padding: 8px 14px; border-radius: 6px; cursor: pointer; } button:disabled { opacity: .5; } article { border-top: 1px solid #e2ebe6; padding: 24px 0; } .content { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; color: #33483f; } form { display: grid; gap: 14px; padding: 20px 0; } label { display: grid; gap: 8px; } input, textarea { padding: 10px; border: 1px solid #ccdad2; border-radius: 6px; } form button { justify-self: end; } .empty { padding: 48px 0; text-align: center; color: #718079; }
</style>
