<template>
  <div class="agent-message-content">
    <div v-if="isTraceActive" class="agent-working" role="status" aria-live="polite">
      <span class="working-mark"><n-icon :size="16"><Loader class="spin" /></n-icon></span>
      <span>{{ !canConfirm && presentation.confirmations.length ? '等待请求发起人确认后继续' : workingLabel }}</span>
    </div>
    <AgentTaskPlan :runtime-trace="runtimeTrace" />
    <AgentTeamOverview :runtime-trace="runtimeTrace" />
    <template v-for="item in presentation.items" :key="item.key">
      <template v-if="item.kind === 'block'">
        <details v-if="item.block.type === 'thinking'" class="agent-thinking" :open="isThinkingBlockActive(runtimeTrace, item.message, item.block)">
          <summary><n-icon :size="15"><Bulb /></n-icon><span>思考过程</span><n-icon class="thinking-chevron" :size="14"><ChevronRight /></n-icon></summary>
          <div class="thinking-body agent-markdown" v-html="renderMarkdown(item.block.thinking || '正在思考…')"></div>
        </details>
        <AgentWorkRecord v-else-if="item.block.type === 'tool_call'" :label="userWorkLabel(item.block.presentation)"
          :state="callState(item.message, item.block)" />
        <div v-if="item.block.type === 'text'" class="agent-markdown" v-html="renderMarkdown(item.block.text)"></div>
        <figure v-else-if="item.block.type === 'data' && dataUrl(item.block)" class="agent-media">
          <img v-if="item.block.source.media_type.startsWith('image/')" :src="dataUrl(item.block)!" :alt="item.block.name || 'Dobby 返回图片'">
          <a v-else :href="dataUrl(item.block)!" target="_blank" rel="noopener noreferrer">{{ item.block.name || '查看结果文件' }}</a>
        </figure>
      </template>
      <AgentCollaborationStep v-else-if="item.kind === 'collaboration'" :step="item.step"
        :active="isTraceActive" :interrupted="isInterrupted" />
      <details v-else-if="item.kind === 'collaboration_feedback'" class="agent-collaboration-feedback">
        <summary><n-icon :size="15"><MessageCircle /></n-icon><strong>{{ item.feedback.name }}的反馈</strong>
          <span v-if="item.feedback.teamName">{{ item.feedback.teamName }}</span>
          <n-icon class="thinking-chevron" :size="14"><ChevronRight /></n-icon>
        </summary>
        <div class="feedback-body agent-markdown" v-html="renderMarkdown(item.feedback.text)"></div>
      </details>
    </template>
    <div v-if="!presentation.answers.length && content" class="agent-markdown" v-html="renderMarkdown(content)"></div>
    <AgentToolCall v-for="entry in presentation.confirmations" :key="entry.key" :call="entry.call"
      :reply-id="entry.replyId" :active="isTraceActive" :can-confirm="canConfirm" :confirmation-busy="confirmationBusy"
      :pending-key="pendingConfirmationKey" @confirm="confirmToolCall" />
    <div v-if="hasError && !isTraceActive" class="agent-runtime-error" role="alert">
      <n-icon :size="16"><AlertTriangle /></n-icon><span>这次处理遇到了问题，请稍后重试。</span>
    </div>
    <p v-else-if="runtimeTrace && !isTraceActive && !presentation.answers.length && !content" class="agent-empty-result">
      {{ isInterrupted ? '本次处理已停止。' : '本次处理已结束，暂时没有可展示的结果。' }}
    </p>

    <footer v-if="runtimeTrace && !isTraceActive && (presentation.answers.length || content)" class="agent-runtime-footer">
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
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NIcon } from 'naive-ui'
import { AlertTriangle, Bulb, ChevronRight, Circle, CircleCheck, Loader, MessageCircle } from '@vicons/tabler'
import MarkdownIt from 'markdown-it'
import AgentToolCall from './AgentToolCall.vue'
import AgentWorkRecord from './AgentWorkRecord.vue'
import AgentTaskPlan from './AgentTaskPlan.vue'
import AgentTeamOverview from './AgentTeamOverview.vue'
import AgentCollaborationStep from './AgentCollaborationStep.vue'
import type { AgentDataBlock, AgentRuntimeMessage, AgentRuntimeTrace, AgentToolCallBlock } from '@/types/agentRuntime'
import { findToolResult, isRuntimeActive, isThinkingBlockActive, toolPresentationState } from '@/utils/agentMessagePresentation'
import { userMessagePresentation, userWorkLabel } from '@/utils/agentUserPresentation'

const props = withDefaults(defineProps<{
  content?: string
  runtimeTrace?: AgentRuntimeTrace | null
  streaming?: boolean
  startingLabel?: string
  markdownRenderer?: (content: string) => string
  assistantName?: string
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

const presentation = computed(() => userMessagePresentation(props.runtimeTrace, props.streaming))
const workingLabel = computed(() => {
  if (props.assistantName && !props.runtimeTrace?.messages.length) return props.startingLabel
  return props.assistantName ? presentation.value.workingLabel.replace(/^Dobby/, props.assistantName) : presentation.value.workingLabel
})
const isTraceActive = computed(() => isRuntimeActive(props.runtimeTrace) || props.streaming)
const isInterrupted = computed(() => props.runtimeTrace?.status === 'interrupted')
function callState(message: AgentRuntimeMessage, call: AgentToolCallBlock) {
  const result = findToolResult(message, call.id)
  if ((!result || result.state === 'running') && isTraceActive.value && props.runtimeTrace?.status === 'awaiting_external_result') return 'external'
  return toolPresentationState(call, result, isTraceActive.value, isInterrupted.value)
}
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
  return '已回复'
})
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
  if (props.markdownRenderer) return props.markdownRenderer(value)
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
.agent-thinking { min-width:0; color:#607b76; font-size:13px; }
.agent-thinking summary { display:flex; align-items:center; gap:8px; padding:8px 3px; cursor:pointer; list-style:none; }
.agent-thinking summary::-webkit-details-marker { display:none; }
.agent-thinking summary:focus-visible { outline:2px solid #177b6d; outline-offset:2px; }
.thinking-chevron { margin-left:auto; }.agent-thinking[open] .thinking-chevron { transform:rotate(90deg); }
.thinking-body { margin:2px 0 8px 10px; padding:6px 12px; border-left:2px solid #d7e5df; }
.agent-collaboration-feedback { min-width:0; border-left:2px solid #c6dcd6; padding-left:10px; font-size:13px; }
.agent-collaboration-feedback summary { display:flex; align-items:center; gap:8px; padding:8px 3px; cursor:pointer; list-style:none; color:#426960; }
.agent-collaboration-feedback summary::-webkit-details-marker { display:none; }
.agent-collaboration-feedback summary:focus-visible { outline:2px solid #177b6d; outline-offset:2px; }
.agent-collaboration-feedback summary>span { color:#6d837c; font-size:12px; }
.agent-collaboration-feedback[open] .thinking-chevron { transform:rotate(90deg); }
.feedback-body { padding:4px 3px 10px; }
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

.agent-working { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid #dce9e4;
  border-radius: 9px; background: #edf5f1; color: #37665a; font-size: 13px; line-height: 1.6; }
.working-mark { display: inline-flex; align-items: center; justify-content: center; color: #177b6d; }
.agent-empty-result { margin: 0; color: #607873; font-size: 13px; line-height: 1.7; }
.agent-media { margin: 0; }.agent-media img { max-width: 100%; max-height: 360px; border-radius: 8px; object-fit: contain; }
.agent-media a { color: #0d7469; font-size: 12px; }
.agent-runtime-error { display: flex; align-items: flex-start; gap: 8px; border: 1px solid #efcfc5; border-radius: 7px;
  padding: 9px 10px; color: #a23f25; background: #fff5f1; font-size: 12px; }
.agent-runtime-footer { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 5px; color: #6d837c; font-size: 12px; }
.agent-runtime-state { display: inline-flex; align-items: center; gap: 4px; color: #4e6e68; }
.agent-runtime-state.running { color: #0b7768; }.agent-runtime-state.interrupted { color: #8a5b19; }.agent-runtime-state.error { color: #a4472d; }
.spin { animation: spin .8s linear infinite; }@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; } }
</style>
