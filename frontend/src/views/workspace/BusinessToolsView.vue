<template>
  <main class="business-tools-page">
    <section class="business-tools-shell">
      <aside class="tool-rail" aria-label="业务工具列表">
        <header class="tool-rail-head">
          <div>
            <span>专业智能体</span>
            <strong>业务工具</strong>
          </div>
          <em>{{ businessTools.length }}</em>
          <p>选择一个专业智能体，围绕当前项目继续分析和处理。</p>
        </header>

        <nav class="tool-list">
          <p v-if="catalogLoading" class="tool-list-state">正在读取 AgentScope 智能体目录…</p>
          <p v-else-if="catalogError" class="tool-list-state error">{{ catalogError }}</p>
          <p v-else-if="!businessTools.length" class="tool-list-state">暂无已发布的业务智能体，请先在 AgentScope 中完成发布。</p>
          <button
            v-for="tool in businessTools"
            :key="tool.id"
            type="button"
            :class="{ active: selectedToolId === tool.id }"
            @click="selectTool(tool.id)"
          >
            <span class="tool-list-icon"><n-icon :size="20"><component :is="tool.icon" /></n-icon></span>
            <span class="tool-list-copy">
              <strong>{{ tool.name }}</strong>
              <small>{{ tool.shortDescription }}</small>
            </span>
            <i aria-hidden="true"></i>
          </button>
        </nav>

      </aside>

      <section class="tool-workspace" aria-label="业务工具对话区">
        <header class="tool-workspace-head">
          <div class="active-tool-icon"><n-icon :size="24"><component :is="selectedTool.icon" /></n-icon></div>
          <div class="active-tool-copy">
            <span><n-icon :size="15"><Robot /></n-icon>专业智能体</span>
            <h1>{{ selectedTool.name }}</h1>
            <p>{{ selectedTool.description }}</p>
          </div>
          <div class="tool-online-state" :class="{ unavailable: !selectedTool.modelReady }"><i></i><span>{{ selectedTool.modelReady ? '可用' : '模型未配置' }}</span></div>
        </header>

        <div ref="threadViewport" class="tool-thread">
          <article v-for="item in activeToolMessages" :key="item.id" :class="['tool-message', item.role]">
            <div class="tool-message-avatar" aria-hidden="true">{{ item.role === 'assistant' ? '管' : '我' }}</div>
            <div class="tool-message-stack">
              <span v-if="item.role === 'assistant'">{{ selectedTool.name }}</span>
              <div class="tool-message-bubble">
                <AgentMessageContent
                  :content="item.content"
                  :runtime-trace="item.runtimeTrace"
                  @confirm="confirmToolCall"
                />
                <div v-if="item.attachments?.length" class="tool-message-files">
                  <span v-for="attachment in item.attachments" :key="attachment.id">
                    <n-icon :size="16"><FileText /></n-icon>
                    <b :title="attachment.name">{{ attachment.name }}</b>
                    <small>{{ formatFileSize(attachment.size) }}</small>
                  </span>
                </div>
              </div>
            </div>
          </article>

          <article v-if="activeStreamingTrace" class="tool-message assistant">
            <div class="tool-message-avatar" aria-hidden="true">管</div>
            <div class="tool-message-stack">
              <span>{{ selectedTool.name }}</span>
              <div class="tool-message-bubble runtime">
                <AgentMessageContent
                  :runtime-trace="activeStreamingTrace"
                  streaming
                  @confirm="confirmToolCall"
                />
              </div>
            </div>
          </article>

          <section v-if="!activeToolMessages.length && !activeStreamingTrace" class="tool-empty-state">
            <div class="tool-empty-icon"><n-icon :size="27"><component :is="selectedTool.icon" /></n-icon></div>
            <span>{{ selectedTool.name }}智能体</span>
            <h2>{{ selectedTool.emptyTitle }}</h2>
            <p>{{ selectedTool.emptyDescription }}</p>
            <div class="tool-starters" aria-label="示例任务">
              <button v-for="starter in selectedTool.starters" :key="starter" type="button" @click="useStarter(starter)">{{ starter }}</button>
            </div>
          </section>
        </div>

        <form class="tool-composer" @submit.prevent="submitToolMessage">
          <div class="tool-composer-entry">
            <div v-if="selectedFiles.length" class="tool-file-queue" aria-label="待发送附件">
              <span v-for="(file, index) in selectedFiles" :key="`${file.name}-${file.lastModified}`">
                <n-icon :size="15"><FileText /></n-icon>
                <b :title="file.name">{{ file.name }}</b>
                <small>{{ formatFileSize(file.size) }}</small>
                <button type="button" :aria-label="`移除附件 ${file.name}`" @click="removeFile(index)">×</button>
              </span>
            </div>
            <div class="tool-composer-row">
              <label class="tool-attach-button" title="添加工程资料或图片">
                <input type="file" multiple @change="selectFiles">
                <n-icon :size="19"><Paperclip /></n-icon>
                <span>添加附件</span>
              </label>
              <textarea
                v-model="command"
                :placeholder="selectedTool.placeholder"
                @keydown.enter.exact.prevent="submitToolMessage"
              ></textarea>
            </div>
          </div>
          <button v-if="submitting" class="tool-send-button stop" type="button" @click="stopToolMessage">
            <n-icon :size="18"><PlayerStop /></n-icon>
            停止
          </button>
          <button v-else class="tool-send-button" type="submit" :disabled="!selectedTool.id || !selectedTool.modelReady || (!command.trim() && !selectedFiles.length)">
            <n-icon :size="18"><Send /></n-icon>
            发送
          </button>
        </form>
      </section>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { NIcon, useMessage } from 'naive-ui'
import { ChartBar, CircleCheck, Database, FileText, Paperclip, PlayerStop, Robot, Route, Send, ShieldCheck } from '@vicons/tabler'
import type { Component } from 'vue'
import api, { type ApiEnvelope } from '@/api/client'
import {
  streamAgentConversationConfirmation,
  streamAgentConversationMessage,
} from '@/api/agentStream'
import AgentMessageContent from '@/components/agent/AgentMessageContent.vue'
import { useAppStore } from '@/stores/app'
import {
  applyAgentRuntimeEvent,
  createEmptyRuntimeTrace,
  runtimeTraceFromExtraData,
  type AgentRuntimeTrace,
  type AgentToolCallBlock,
  type ApiAgentMessage,
} from '@/types/agentRuntime'

type AgentCatalogItem = {
  id: string
  name: string
  description: string
  category: string
  role: 'global_main' | 'business' | 'system_internal'
  enabled: boolean
  published: boolean
  invitable: boolean
  model_ready: boolean
  sort_order: number
  permission_mode: string
}
type AgentCatalog = {
  global_main: AgentCatalogItem | null
  business_agents: AgentCatalogItem[]
  total: number
}
type ApiAgentConversation = {
  id: number
  project_id: number
  user_id: number
  agent_id: string
  agent_name: string
  conversation_type: 'general' | 'business'
  title: string
  agentscope_session_id?: string | null
  status: string
}
type BusinessTool = {
  id: string
  name: string
  shortDescription: string
  description: string
  emptyTitle: string
  emptyDescription: string
  placeholder: string
  starters: string[]
  icon: Component
  modelReady: boolean
}
type ToolMessage = {
  id: string
  role: 'assistant' | 'user'
  content: string
  attachments?: Array<{ id: string; name: string; size: number }>
  runtimeTrace?: AgentRuntimeTrace | null
}

const store = useAppStore()
const message = useMessage()
const businessTools = ref<BusinessTool[]>([])
const selectedToolId = ref('')
const command = ref('')
const selectedFiles = ref<File[]>([])
const submitting = ref(false)
const catalogLoading = ref(false)
const catalogError = ref('')
const threadViewport = ref<HTMLElement | null>(null)
const toolMessages = ref<Record<string, ToolMessage[]>>({})
const conversationIds = ref<Record<string, number>>({})
const streamingTraces = ref<Record<string, AgentRuntimeTrace | null>>({})
const emptyTool: BusinessTool = {
  id: '',
  name: '业务智能体',
  shortDescription: '',
  description: '请先在 AgentScope 中发布业务智能体。',
  emptyTitle: '暂无可用业务智能体',
  emptyDescription: '配置为“业务智能体”，启用并发布后会自动出现在这里。',
  placeholder: '暂无可用智能体',
  starters: [],
  icon: Robot,
  modelReady: false,
}

const selectedTool = computed(() => businessTools.value.find(tool => tool.id === selectedToolId.value) || businessTools.value[0] || emptyTool)
const activeToolMessages = computed(() => toolMessages.value[selectedTool.value.id] ?? [])
const activeStreamingTrace = computed(() => streamingTraces.value[selectedTool.value.id] ?? null)

function iconForAgent(item: AgentCatalogItem): Component {
  const text = `${item.category} ${item.name}`
  if (/安全|隐患/.test(text)) return ShieldCheck
  if (/报告|资料|文档|合同/.test(text)) return FileText
  if (/趋势|预测|进度/.test(text)) return ChartBar
  if (/风险|诊断|审查/.test(text)) return Route
  if (/数据|统计|分析/.test(text)) return Database
  if (/审核|复核|质量/.test(text)) return CircleCheck
  return Robot
}

function mapAgentToTool(item: AgentCatalogItem): BusinessTool {
  const description = item.description || `${item.name}已由 AgentScope 发布。`
  return {
    id: item.id,
    name: item.name,
    shortDescription: description,
    description,
    emptyTitle: `向${item.name}说明你的任务`,
    emptyDescription: `当前对话将直接交给${item.name}处理，并自动携带当前项目的权限范围与数据摘要。`,
    placeholder: `输入需要${item.name}处理的项目问题`,
    starters: [
      `请结合当前项目说明你能协助处理哪些事项`,
      `检查当前项目最需要关注的问题并给出依据`,
      `给出下一步可执行的处理建议`,
    ],
    icon: iconForAgent(item),
    modelReady: item.model_ready,
  }
}

async function loadCatalog() {
  catalogLoading.value = true
  catalogError.value = ''
  try {
    const response = await api.get<ApiEnvelope<AgentCatalog>>('/agents/catalog')
    businessTools.value = response.data.data.business_agents.map(mapAgentToTool)
    if (!businessTools.value.some(tool => tool.id === selectedToolId.value)) {
      selectedToolId.value = businessTools.value[0]?.id ?? ''
    }
    if (selectedToolId.value && store.currentProjectId) await loadToolConversation(selectedToolId.value)
  } catch (error: any) {
    catalogError.value = error?.response?.data?.detail || '无法读取 AgentScope 智能体目录。'
  } finally {
    catalogLoading.value = false
  }
}

async function loadToolConversation(agentId: string) {
  if (!agentId || !store.currentProjectId) return
  const response = await api.get<ApiEnvelope<ApiAgentConversation[]>>(
    `/projects/${store.currentProjectId}/agent-conversations`,
    { params: { conversation_type: 'business', agent_id: agentId } },
  )
  const conversation = response.data.data[0]
  if (!conversation) {
    toolMessages.value = { ...toolMessages.value, [agentId]: [] }
    return
  }
  conversationIds.value = { ...conversationIds.value, [agentId]: conversation.id }
  const messagesResponse = await api.get<ApiEnvelope<ApiAgentMessage[]>>(`/agent-conversations/${conversation.id}/messages`)
  toolMessages.value = {
    ...toolMessages.value,
    [agentId]: messagesResponse.data.data.map(item => ({
      id: String(item.id),
      role: item.role,
      content: item.content,
      runtimeTrace: runtimeTraceFromExtraData(item.extra_data),
    })),
  }
}

async function ensureConversation(agentId: string) {
  const existing = conversationIds.value[agentId]
  if (existing) return existing
  const response = await api.post<ApiEnvelope<ApiAgentConversation>>(
    `/projects/${store.currentProjectId}/agent-conversations`,
    { conversation_type: 'business', agent_id: agentId },
  )
  conversationIds.value = { ...conversationIds.value, [agentId]: response.data.data.id }
  return response.data.data.id
}

function selectTool(agentId: string) {
  selectedToolId.value = agentId
  command.value = ''
  selectedFiles.value = []
  void loadToolConversation(agentId)
  nextTick(() => threadViewport.value?.scrollTo({ top: 0 }))
}

function useStarter(starter: string) {
  command.value = starter
}

function selectFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const accepted = Array.from(input.files || []).filter(file => file.size <= 50 * 1024 * 1024)
  const rejected = Array.from(input.files || []).length - accepted.length
  selectedFiles.value = [...selectedFiles.value, ...accepted]
    .filter((file, index, files) => files.findIndex(item => item.name === file.name && item.size === file.size && item.lastModified === file.lastModified) === index)
    .slice(0, 8)
  input.value = ''
  if (rejected) message.warning('单个附件不能超过 50 MB。')
}

function removeFile(index: number) {
  selectedFiles.value = selectedFiles.value.filter((_, fileIndex) => fileIndex !== index)
}

function formatFileSize(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

async function submitToolMessage() {
  const text = command.value.trim() || (selectedFiles.value.length ? '请分析我上传的资料' : '')
  if (!text || submitting.value) return
  if (!store.currentProjectId) {
    message.warning('请先选择项目。')
    return
  }
  if (!selectedTool.value.id || !selectedTool.value.modelReady) {
    message.warning('请先选择已配置固定模型的业务智能体。')
    return
  }
  const files = [...selectedFiles.value]
  submitting.value = true
  try {
    for (const file of files) await store.uploadAttachment(file, `业务工具/${selectedTool.value.name}`)
    const timestamp = Date.now()
    const attachments = files.map(file => ({ id: `${file.name}-${file.lastModified}`, name: file.name, size: file.size }))
    const agentId = selectedTool.value.id
    const current = [...(toolMessages.value[agentId] ?? [])]
    current.push({ id: `${agentId}-user-${timestamp}`, role: 'user', content: text, attachments: attachments.length ? attachments : undefined })
    toolMessages.value = { ...toolMessages.value, [agentId]: current }
    const conversationId = await ensureConversation(agentId)
    streamingTraces.value = {
      ...streamingTraces.value,
      [agentId]: createEmptyRuntimeTrace(),
    }
    command.value = ''
    selectedFiles.value = []
    const completion: { message: ApiAgentMessage | null } = { message: null }
    await streamAgentConversationMessage(conversationId, text, {
      onEvent: async runtimeEvent => {
        streamingTraces.value = {
          ...streamingTraces.value,
          [agentId]: applyAgentRuntimeEvent(streamingTraces.value[agentId], runtimeEvent),
        }
        await nextTick()
        threadViewport.value?.scrollTo({ top: threadViewport.value.scrollHeight })
      },
      onDone: payload => {
        completion.message = payload.message
      },
    })
    if (completion.message) {
      current.push({
        id: String(completion.message.id || `${agentId}-assistant-${timestamp + 1}`),
        role: 'assistant',
        content: completion.message.content,
        runtimeTrace: runtimeTraceFromExtraData(completion.message.extra_data),
      })
      toolMessages.value = { ...toolMessages.value, [agentId]: current }
      streamingTraces.value = { ...streamingTraces.value, [agentId]: null }
    }
    await nextTick()
    threadViewport.value?.scrollTo({ top: threadViewport.value.scrollHeight, behavior: 'smooth' })
  } catch (error: any) {
    message.error(error?.response?.data?.detail || error?.message || '智能体处理失败，请检查 AgentScope 状态后重试。')
  } finally {
    submitting.value = false
  }
}

async function stopToolMessage() {
  const conversationId = conversationIds.value[selectedTool.value.id]
  if (!conversationId) return
  try {
    await api.post(`/agent-conversations/${conversationId}/interrupt`)
    message.info('已请求停止，正在等待智能体安全结束当前步骤。')
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '停止智能体失败。')
  }
}

async function confirmToolCall(
  replyId: string,
  toolCall: AgentToolCallBlock,
  confirmed: boolean,
) {
  const agentId = selectedTool.value.id
  const conversationId = conversationIds.value[agentId]
  if (!conversationId) return
  if (submitting.value) return
  submitting.value = true
  streamingTraces.value = {
    ...streamingTraces.value,
    [agentId]: createEmptyRuntimeTrace(),
  }
  message.info(
    confirmed
      ? `正在允许「${toolCall.name}」执行。`
      : `正在拒绝「${toolCall.name}」。`,
  )
  try {
    await streamAgentConversationConfirmation(
      conversationId,
      {
        reply_id: replyId,
        tool_call: toolCall,
        confirmed,
      },
      {
        onAccepted: payload => {
          message.success(
            payload.message
            || (
              confirmed
                ? `已允许「${toolCall.name}」，智能体正在继续执行。`
                : `已拒绝「${toolCall.name}」，智能体正在处理确认结果。`
            ),
          )
        },
        onEvent: async runtimeEvent => {
          streamingTraces.value = {
            ...streamingTraces.value,
            [agentId]: applyAgentRuntimeEvent(
              streamingTraces.value[agentId],
              runtimeEvent,
            ),
          }
          await nextTick()
          threadViewport.value?.scrollTo({
            top: threadViewport.value.scrollHeight,
          })
        },
      },
    )
    await loadToolConversation(agentId)
  } catch (error: any) {
    message.error(
      error?.response?.data?.detail
      || error?.message
      || '提交人工确认失败。',
    )
  } finally {
    streamingTraces.value = {
      ...streamingTraces.value,
      [agentId]: null,
    }
    submitting.value = false
  }
}

onMounted(loadCatalog)
watch(() => store.currentProjectId, () => {
  conversationIds.value = {}
  toolMessages.value = {}
  streamingTraces.value = {}
  if (selectedToolId.value) void loadToolConversation(selectedToolId.value)
})
</script>

<style scoped>
.business-tools-page {
  height: calc(100dvh - var(--header-height, 56px));
  min-width: 0;
  box-sizing: border-box;
  padding: 18px;
  overflow: hidden;
  background: radial-gradient(circle at 15% 0%, rgba(15, 118, 110, .07), transparent 30rem), linear-gradient(180deg, #f6f7f3, #edf1ee);
}
.business-tools-shell {
  display: grid;
  height: 100%;
  min-width: 0;
  min-height: 0;
  grid-template-columns: minmax(280px, 30%) minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid rgba(20, 45, 54, .1);
  border-radius: 9px;
  background: rgba(255, 255, 255, .94);
  box-shadow: 0 18px 42px rgba(28, 48, 44, .06);
}
.tool-rail { display: grid; min-width: 0; min-height: 0; grid-template-rows: auto minmax(0, 1fr); border-right: 1px solid #dfe9e5; background: #f9fbfa; }
.tool-rail-head { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 5px 12px; padding: 17px 18px 15px; border-bottom: 1px solid #e2eae7; }
.tool-rail-head > div { display: grid; }
.tool-rail-head span { color: #0f766e; font-size: 12px; font-weight: 800; }
.tool-rail-head strong { margin-top: 3px; color: #173b38; font-size: 18px; font-weight: 850; }
.tool-rail-head em { display: grid; min-width: 28px; height: 28px; place-items: center; border-radius: 6px; color: #0f766e; background: #e3f1ec; font-size: 13px; font-style: normal; font-weight: 850; font-variant-numeric: tabular-nums; }
.tool-rail-head p { grid-column: 1 / -1; margin: 4px 0 0; color: #71857f; font-size: 12px; line-height: 1.5; }
.tool-list { min-height: 0; padding: 7px 0; overflow-y: auto; overscroll-behavior: contain; }
.tool-list-state { margin: 0; padding: 20px 18px; color: #71857f; font-size: 12px; line-height: 1.7; }
.tool-list-state.error { color: #a64025; }
.tool-list button { position: relative; display: grid; width: 100%; min-height: 76px; grid-template-columns: 42px minmax(0, 1fr) 7px; align-items: center; gap: 11px; padding: 10px 15px; border: 0; border-bottom: 1px solid rgba(31, 66, 62, .065); color: inherit; background: transparent; font: inherit; text-align: left; cursor: pointer; transition: background .2s ease, box-shadow .2s ease, transform .2s ease; }
.tool-list button::before { position: absolute; inset: 9px auto 9px 0; width: 3px; border-radius: 0 3px 3px 0; content: ''; background: transparent; }
.tool-list button:hover { background: #f0f6f3; }
.tool-list button:active { transform: scale(.99); }
.tool-list button.active { background: #e9f4f0; box-shadow: inset -1px 0 rgba(15, 118, 110, .12); }
.tool-list button.active::before { background: #0f766e; }
.tool-list button:focus-visible, .tool-composer button:focus-visible, .tool-composer textarea:focus-visible { outline: 2px solid #0f766e; outline-offset: -2px; }
.tool-list-icon { display: grid; width: 40px; height: 40px; place-items: center; border: 1px solid #cfe1db; border-radius: 8px; color: #0f766e; background: #edf7f4; }
.tool-list button.active .tool-list-icon { color: #fff; border-color: #0f766e; background: #0f766e; }
.tool-list-copy { min-width: 0; }
.tool-list-copy strong { display: block; color: #254944; font-size: 14px; font-weight: 800; }
.tool-list-copy small { display: block; overflow: hidden; margin-top: 5px; color: #71857f; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.tool-list button > i { width: 6px; height: 6px; border-radius: 50%; background: #c2d0cc; }
.tool-list button.active > i { background: #16a277; box-shadow: 0 0 0 4px rgba(22, 162, 119, .1); }
.tool-workspace { display: grid; min-width: 0; min-height: 0; grid-template-rows: auto minmax(0, 1fr) auto; background: radial-gradient(circle at 92% 8%, rgba(15, 118, 110, .05), transparent 24rem), #fff; }
.tool-workspace-head { display: grid; grid-template-columns: 48px minmax(0, 1fr) auto; align-items: center; gap: 13px; padding: 15px 18px; border-bottom: 1px solid #e2eae7; }
.active-tool-icon { display: grid; width: 46px; height: 46px; place-items: center; border-radius: 9px; color: #e3f3ee; background: #173f3d; box-shadow: 0 9px 20px rgba(23, 63, 61, .16); }
.active-tool-copy { min-width: 0; }
.active-tool-copy > span { display: inline-flex; align-items: center; gap: 5px; color: #0f766e; font-size: 12px; font-weight: 800; }
.active-tool-copy h1 { margin: 4px 0 2px; color: #153733; font-size: 19px; font-weight: 860; letter-spacing: -.015em; }
.active-tool-copy p { overflow: hidden; margin: 0; color: #6e827d; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.tool-online-state { display: inline-flex; align-items: center; gap: 7px; color: #60766f; font-size: 12px; }
.tool-online-state i { width: 7px; height: 7px; border-radius: 50%; background: #16a277; box-shadow: 0 0 0 4px rgba(22, 162, 119, .1); }
.tool-online-state.unavailable { color: #a46600; }
.tool-online-state.unavailable i { background: #d48a18; box-shadow: 0 0 0 4px rgba(212, 138, 24, .12); }
.tool-thread { display: flex; min-height: 0; flex-direction: column; gap: 13px; padding: 18px clamp(18px, 3vw, 40px) 28px; overflow-y: auto; overscroll-behavior: contain; }
.tool-message { display: grid; max-width: min(830px, 94%); grid-template-columns: 32px minmax(0, 1fr); align-items: start; gap: 10px; }
.tool-message.user { align-self: flex-end; grid-template-columns: minmax(0, 1fr) 32px; }
.tool-message-avatar { display: grid; width: 32px; height: 32px; place-items: center; border-radius: 8px; color: #dff1ec; background: #173f3d; font-size: 12px; font-weight: 800; }
.tool-message.user .tool-message-avatar { grid-column: 2; color: #fff; background: #c95622; }
.tool-message.user .tool-message-stack { grid-column: 1; grid-row: 1; }
.tool-message-stack { min-width: 0; }
.tool-message-stack > span { display: block; margin: 0 0 5px 2px; color: #c45528; font-size: 12px; font-weight: 800; }
.tool-message-bubble { padding: 13px 15px; border: 1px solid #dce7e3; border-radius: 5px 10px 10px; background: #fff; box-shadow: 0 8px 22px rgba(26, 55, 52, .055); }
.tool-message.user .tool-message-bubble { border-radius: 10px 5px 10px 10px; border-color: #efd5c8; background: #fff8f4; }
.tool-message-bubble p { max-width: 72ch; margin: 0; color: #385651; font-size: 14px; line-height: 1.65; white-space: pre-line; }
.tool-message-files, .tool-file-queue { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.tool-message-files > span, .tool-file-queue > span { display: inline-flex; min-width: 0; align-items: center; gap: 6px; padding: 6px 8px; border-radius: 5px; color: #48645e; background: #eef5f2; font-size: 12px; }
.tool-message-files b, .tool-file-queue b { max-width: 210px; overflow: hidden; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.tool-message-files small, .tool-file-queue small { color: #82938e; font-size: 12px; white-space: nowrap; }
.tool-empty-state { display: grid; width: min(680px, 92%); min-height: 360px; place-content: center; justify-items: center; box-sizing: border-box; margin: auto; padding: 42px 24px; text-align: center; }
.tool-empty-icon { display: grid; width: 56px; height: 56px; place-items: center; border-radius: 13px; color: #e3f3ee; background: #173f3d; box-shadow: 0 12px 28px rgba(23, 63, 61, .16); }
.tool-empty-state > span { margin-top: 15px; color: #0f766e; font-size: 12px; font-weight: 800; }
.tool-empty-state h2 { margin: 6px 0 0; color: #244641; font-size: 19px; font-weight: 850; letter-spacing: -.01em; }
.tool-empty-state > p { max-width: 48ch; margin: 8px 0 0; color: #71857f; font-size: 13px; line-height: 1.65; }
.tool-starters { display: flex; max-width: 650px; margin-top: 19px; flex-wrap: wrap; justify-content: center; gap: 7px; }
.tool-starters button { padding: 7px 9px; border: 1px solid #c9ddd7; border-radius: 6px; color: #0e6c65; background: #fff; font: inherit; font-size: 12px; font-weight: 750; cursor: pointer; transition: transform .18s ease, border-color .18s ease, background .18s ease; }
.tool-starters button:hover { transform: translateY(-1px); border-color: #0f766e; background: #f2f9f6; }
.tool-composer { display: grid; grid-template-columns: minmax(0, 1fr) 86px; gap: 8px; padding: 12px 16px 15px; border-top: 1px solid #e1e9e6; background: rgba(252, 253, 253, .96); }
.tool-composer-entry { min-width: 0; padding: 6px 8px 7px; border: 1px solid #cddbd7; border-radius: 7px; background: #fff; transition: border-color .18s ease, box-shadow .18s ease; }
.tool-composer-entry:focus-within { border-color: #0f766e; box-shadow: 0 0 0 3px rgba(15, 118, 110, .09); }
.tool-file-queue { margin: 0 0 6px; padding-bottom: 6px; border-bottom: 1px solid #e6eeeb; }
.tool-file-queue button { display: grid; width: 20px; height: 20px; place-items: center; border: 0; border-radius: 4px; color: #78908a; background: transparent; font: inherit; cursor: pointer; }
.tool-file-queue button:hover { color: #b94623; background: #fae8e0; }
.tool-composer-row { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: end; gap: 8px; }
.tool-attach-button { display: inline-flex; min-height: 38px; align-items: center; gap: 6px; padding: 0 9px; border-radius: 5px; color: #58716b; background: #f0f5f3; font-size: 12px; font-weight: 750; cursor: pointer; }
.tool-attach-button:hover { color: #0f766e; background: #e5f1ed; }
.tool-attach-button input { position: absolute; width: 1px; height: 1px; overflow: hidden; opacity: 0; pointer-events: none; }
.tool-composer textarea { width: 100%; min-height: 38px; max-height: 92px; box-sizing: border-box; padding: 8px 5px; border: 0; outline: 0; color: #294844; background: transparent; font: inherit; font-size: 14px; line-height: 1.5; resize: none; }
.tool-send-button { display: inline-flex; align-items: center; justify-content: center; gap: 5px; border: 0; border-radius: 7px; color: #fff; background: #c95622; font: inherit; font-size: 13px; font-weight: 800; cursor: pointer; transition: transform .18s ease, background .18s ease, box-shadow .18s ease; }
.tool-send-button:hover { transform: translateY(-1px); background: #b94a1b; box-shadow: 0 9px 18px rgba(201, 86, 34, .18); }
.tool-send-button.stop { background:#3e5f5a; }
.tool-send-button.stop:hover { background:#304f4a; box-shadow:0 9px 18px rgba(48,79,74,.16); }
.tool-send-button:active { transform: translateY(1px) scale(.98); }
.tool-send-button:disabled { opacity: .45; cursor: not-allowed; transform: none; box-shadow: none; }
@media (max-width: 980px) {
  .business-tools-page { height: auto; min-height: calc(100dvh - var(--header-height, 56px)); overflow: visible; }
  .business-tools-shell { min-height: 820px; grid-template-columns: minmax(240px, 34%) minmax(0, 1fr); }
  .tool-message-bubble p, .tool-composer textarea { font-size: 13px; }
}
@media (max-width: 720px) {
  .business-tools-page { padding: 10px; }
  .business-tools-shell { display: block; min-height: 0; overflow: visible; }
  .tool-rail { border-right: 0; border-bottom: 1px solid #dfe9e5; }
  .tool-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); max-height: none; padding: 7px; }
  .tool-list button { min-height: 68px; border: 1px solid transparent; border-radius: 6px; }
  .tool-list button::before, .tool-list button > i { display: none; }
  .tool-list button.active { border-color: #bed8d0; }
  .tool-workspace { min-height: 720px; }
  .tool-workspace-head { grid-template-columns: 42px minmax(0, 1fr); }
  .active-tool-icon { width: 40px; height: 40px; }
  .tool-online-state { display: none; }
  .active-tool-copy p { white-space: normal; }
  .tool-thread { padding-inline: 12px; }
  .tool-empty-state { width: 100%; min-height: 320px; padding-inline: 18px; }
  .tool-composer { grid-template-columns: 1fr; }
  .tool-send-button { min-height: 42px; }
}
</style>
