<template>
  <div class="agent-message-content">
    <template v-for="item in conversationItems" :key="item.key">
      <AgentCollaborationStep v-if="item.kind === 'collaboration'" :step="item.step"
        :active="isTraceActive" :interrupted="isInterrupted" :can-confirm="canConfirm"
        :confirmation-busy="confirmationBusy" :pending-key="pendingConfirmationKey" @confirm="confirmToolCall" />
      <div v-else-if="item.kind === 'error'" class="agent-runtime-error" role="alert">
        <n-icon :size="16"><AlertTriangle /></n-icon>
        <span>{{ item.message.error?.message || '处理失败，请重试。' }}</span>
      </div>
      <template v-else-if="item.kind === 'block'">
        <div v-if="item.block.type === 'text'" class="agent-markdown" v-html="renderMarkdown(item.block.text)"></div>
        <details v-else-if="item.block.type === 'thinking'" class="agent-thinking"
          :open="isThinkingBlockActive(runtimeTrace, item.message, item.block)">
          <summary>
            <span><n-icon :size="14"><Bulb /></n-icon>思考过程</span>
            <span class="agent-thinking-actions">
              <em v-if="isThinkingBlockActive(runtimeTrace, item.message, item.block)">思考中</em>
              <n-icon class="agent-thinking-chevron" :size="14" aria-hidden="true"><ChevronRight /></n-icon>
            </span>
          </summary>
          <div>{{ item.block.thinking || '正在思考…' }}</div>
        </details>
        <AgentToolCall v-else-if="item.block.type === 'tool_call'" :call="item.block"
          :result="findToolResult(item.message, item.block.id)" :reply-id="item.message.id"
          :active="isMessageRunning(item.message)" :interrupted="isInterrupted || item.message.finished_reason === 'interrupted'"
          :can-confirm="canConfirm" :confirmation-busy="confirmationBusy" :pending-key="pendingConfirmationKey"
          @confirm="confirmToolCall" />
        <figure v-else-if="item.block.type === 'data' && dataUrl(item.block)" class="agent-media">
          <img v-if="item.block.source.media_type.startsWith('image/')" :src="dataUrl(item.block)!"
            :alt="item.block.name || '智能体返回图片'">
          <a v-else :href="dataUrl(item.block)!" target="_blank" rel="noopener noreferrer">{{ item.block.name || '查看智能体返回文件' }}</a>
        </figure>
      </template>
    </template>

    <div v-if="!conversationItems.length && content" class="agent-markdown" v-html="renderMarkdown(content)"></div>
    <div v-if="isTraceActive && !conversationItems.length" class="agent-starting" role="status" aria-live="polite">
      <n-icon :size="14"><Loader class="spin" /></n-icon>{{ startingLabel }}
    </div>

    <footer v-if="runtimeTrace && conversationItems.length" class="agent-runtime-footer">
      <span class="agent-runtime-state" :class="{ running: isTraceActive, error: hasError, interrupted: isInterrupted }">
        <n-icon :size="13">
          <Loader v-if="isTraceActive" class="spin" />
          <AlertTriangle v-else-if="hasError" />
          <Circle v-else-if="isInterrupted" />
          <CircleCheck v-else />
        </n-icon>
        {{ statusLabel }}
      </span>
      <span v-if="elapsedLabel">{{ elapsedLabel }}</span>
      <div v-if="modelNames.length || usage" class="agent-runtime-metrics">
        <span v-if="modelNames.length" class="agent-runtime-model" :title="modelNames.join('、')">{{ modelNames.join('、') }}</span>
        <span v-if="usage">↑ {{ formatNumber(usage.input) }} · ↓ {{ formatNumber(usage.output) }}</span>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NIcon } from 'naive-ui'
import { AlertTriangle, Bulb, ChevronRight, Circle, CircleCheck, Loader } from '@vicons/tabler'
import MarkdownIt from 'markdown-it'
import AgentCollaborationStep from './AgentCollaborationStep.vue'
import AgentToolCall from './AgentToolCall.vue'
import type { AgentDataBlock, AgentRuntimeMessage, AgentRuntimeTrace, AgentToolCallBlock } from '@/types/agentRuntime'
import { agentConversationItems, findToolResult, isRuntimeActive, isThinkingBlockActive } from '@/utils/agentMessagePresentation'

const props = withDefaults(defineProps<{
  content?: string
  runtimeTrace?: AgentRuntimeTrace | null
  streaming?: boolean
  startingLabel?: string
  canConfirm?: boolean
  confirmationBusy?: boolean
}>(), {
  content: '', runtimeTrace: null, streaming: false, startingLabel: '正在处理请求…',
  canConfirm: true, confirmationBusy: false,
})
const emit = defineEmits<{ confirm: [replyId: string, toolCall: AgentToolCallBlock, confirmed: boolean] }>()
const pendingConfirmationKey = ref('')
const confirmationBusy = computed(() => props.confirmationBusy || Boolean(pendingConfirmationKey.value))
function confirmToolCall(replyId: string, toolCall: AgentToolCallBlock, confirmed: boolean) {
  if (confirmationBusy.value || !props.canConfirm || !isTraceActive.value) return
  pendingConfirmationKey.value = `${replyId}:${toolCall.id}:${confirmed ? 'allow' : 'deny'}`
  emit('confirm', replyId, toolCall, confirmed)
}
watch(() => props.confirmationBusy, value => {
  if (!value) pendingConfirmationKey.value = ''
})
watch(() => props.runtimeTrace?.status, () => {
  if (!isRuntimeActive(props.runtimeTrace)) pendingConfirmationKey.value = ''
})

const conversationItems = computed(() => agentConversationItems(props.runtimeTrace))
const isTraceActive = computed(() => isRuntimeActive(props.runtimeTrace) || props.streaming)
const isInterrupted = computed(() => props.runtimeTrace?.status === 'interrupted')
const lastMessage = computed(() => {
  const messages = props.runtimeTrace?.messages.filter(message => message.role === 'assistant') || []
  return messages[messages.length - 1]
})
const hasError = computed(() => ['error', 'failed'].includes(props.runtimeTrace?.status || '')
  || Boolean(lastMessage.value?.error) || lastMessage.value?.finished_reason === 'exceed_max_iters')
const statusLabel = computed(() => {
  if (isInterrupted.value) return '已停止'
  if (hasError.value) return '处理失败'
  if (props.runtimeTrace?.status === 'awaiting_permission') return '等待确认'
  if (props.runtimeTrace?.status === 'awaiting_external_result') return '等待操作结果'
  if (isTraceActive.value) return '处理中'
  return '已完成'
})
function isMessageRunning(message: AgentRuntimeMessage) {
  return isTraceActive.value && !message.finished_at
}

const now = ref(Date.now())
let clock: ReturnType<typeof setInterval> | null = null
onMounted(() => { clock = setInterval(() => { now.value = Date.now() }, 1000) })
onBeforeUnmount(() => { if (clock) clearInterval(clock) })
const elapsedLabel = computed(() => {
  const start = Date.parse(props.runtimeTrace?.turnStartedAt || props.runtimeTrace?.messages[0]?.created_at || '')
  const finished = props.runtimeTrace?.turnFinishedAt || (!isTraceActive.value ? lastMessage.value?.finished_at : null)
  const end = finished ? Date.parse(finished) : isTraceActive.value ? now.value : NaN
  if (!Number.isFinite(start) || !Number.isFinite(end)) return ''
  const seconds = Math.max(0, Math.round((end - start) / 1000))
  return `总耗时 ${seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`}`
})
const modelNames = computed(() => props.runtimeTrace?.modelNames.length
  ? props.runtimeTrace.modelNames : lastMessage.value?.model_names || [])
const usage = computed(() => {
  const messages = props.runtimeTrace?.messages.filter(message => message.role === 'assistant' && message.usage) || []
  return messages.length ? messages.reduce((total, message) => ({
    input: total.input + (message.usage?.input_tokens || 0), output: total.output + (message.usage?.output_tokens || 0),
  }), { input: 0, output: 0 }) : null
})
const formatNumber = (value: number) => new Intl.NumberFormat('zh-CN', { notation: value > 9999 ? 'compact' : 'standard' }).format(value)
function dataUrl(block: AgentDataBlock) {
  if (block.source.type === 'url') return block.source.url || null
  return block.source.data ? `data:${block.source.media_type};base64,${block.source.data}` : null
}

const markdown = new MarkdownIt({ html: false, linkify: true, breaks: true })
const defaultLinkOpen = markdown.renderer.rules.link_open
markdown.renderer.rules.link_open = (tokens, index, options, env, self) => {
  tokens[index].attrSet('target', '_blank')
  tokens[index].attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen ? defaultLinkOpen(tokens, index, options, env, self) : self.renderToken(tokens, index, options)
}
const markdownCache = new Map<string, string>()
function renderMarkdown(value: string) {
  const source = value || ''
  const cached = markdownCache.get(source)
  if (cached !== undefined) return cached
  const rendered = markdown.render(source)
  if (markdownCache.size >= 256) markdownCache.delete(markdownCache.keys().next().value!)
  markdownCache.set(source, rendered)
  return rendered
}
</script>

<style scoped>
.agent-message-content { display: grid; min-width: 0; gap: 8px; color: inherit; }
.agent-markdown { min-width:0; color:inherit; font-size:13px; line-height:1.72; overflow-wrap:anywhere; }
.agent-markdown :deep(p) { margin:0 0 .72em; white-space:normal; }
.agent-markdown :deep(p:last-child) { margin-bottom:0; }
.agent-markdown :deep(ul),.agent-markdown :deep(ol) { margin:.5em 0; padding-left:1.5em; }
.agent-markdown :deep(li) { margin:.2em 0; }
.agent-markdown :deep(h1),.agent-markdown :deep(h2),.agent-markdown :deep(h3) { margin:.9em 0 .45em; color:#183d38; line-height:1.35; }
.agent-markdown :deep(h1) { font-size:18px; }.agent-markdown :deep(h2) { font-size:16px; }.agent-markdown :deep(h3) { font-size:14px; }
.agent-markdown :deep(blockquote) { margin:.65em 0; border-left:3px solid #8abbb0; padding:.25em .8em; color:#607b76; background:#f5faf8; }
.agent-markdown :deep(code) { border-radius:4px; padding:2px 5px; color:#91501f; background:#f4eee8; font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace; }
.agent-markdown :deep(pre) { max-width:100%; margin:.7em 0; overflow:auto; border:1px solid #dbe6e3; border-radius:7px; padding:11px 12px; background:#f7faf9; }
.agent-markdown :deep(pre code) { padding:0; color:#294944; background:transparent; }
.agent-markdown :deep(table) { display:block; width:100%; max-width:100%; overflow:auto; border-collapse:collapse; }
.agent-markdown :deep(th),.agent-markdown :deep(td) { border:1px solid #dbe5e2; padding:6px 9px; text-align:left; }
.agent-markdown :deep(a) { color:#0b766b; text-decoration:underline; text-underline-offset:2px; }

.agent-thinking { min-width: 0; color: #607873; }
.agent-thinking summary { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 7px 2px; cursor: pointer; list-style: none; font-size: 12px; }
.agent-thinking summary::-webkit-details-marker { display: none; }
.agent-thinking summary span { display: flex; align-items: center; gap: 8px; }
.agent-thinking summary em { font-size: 12px; font-style: normal; }
.agent-thinking-actions { flex-shrink: 0; }
.agent-thinking-chevron { color: #6f847e; transition: transform .15s ease; }
.agent-thinking[open] > summary .agent-thinking-chevron { transform: rotate(90deg); }
.agent-thinking summary:focus-visible { outline: 2px solid #177b6d; outline-offset: 2px; }
.agent-thinking > div { margin-left: 10px; padding: 8px 0 8px 17px; border-left: 1px solid #d7e5df;
  font-size: 12px; line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }
.agent-media { margin: 0; }.agent-media img { max-width: 100%; max-height: 360px; border-radius: 8px; object-fit: contain; }
.agent-media a { color: #0d7469; font-size: 12px; }
.agent-runtime-error { display: flex; align-items: flex-start; gap: 8px; border: 1px solid #efcfc5; border-radius: 7px;
  padding: 9px 10px; color: #a23f25; background: #fff5f1; font-size: 12px; }
.agent-runtime-footer { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 5px; color: #6d837c; font-size: 12px; }
.agent-runtime-state { display: inline-flex; align-items: center; gap: 4px; color: #4e6e68; }
.agent-runtime-state.running { color: #0b7768; }.agent-runtime-state.interrupted { color: #8a5b19; }.agent-runtime-state.error { color: #a4472d; }
.agent-runtime-metrics { display: flex; flex-wrap: wrap; min-width: 0; gap: 8px; margin-left: auto; font-variant-numeric: tabular-nums; }
.agent-runtime-model { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-starting { display: flex; align-items: center; gap: 8px; min-height: 28px; color: #607873; font-size: 12px; }
.spin { animation: spin .8s linear infinite; }@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; }.agent-thinking-chevron { transition: none; } }
</style>
