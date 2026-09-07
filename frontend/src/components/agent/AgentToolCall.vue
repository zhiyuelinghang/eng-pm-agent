<template>
  <details class="agent-execution-step agent-tool" :open="state === 'asking'">
    <summary>
      <n-icon :size="16"><Tool /></n-icon>
      <span class="step-title">
        <strong>{{ agentToolLabel(call.name) }}</strong>
        <small v-if="description">{{ description }}</small>
      </span>
      <span class="step-state" :class="`state-${state}`">
        <n-icon v-if="state === 'running'" :size="13"><Loader class="spin" /></n-icon>
        {{ stateLabel }}
      </span>
      <n-icon class="step-chevron" :size="14"><ChevronRight /></n-icon>
    </summary>
    <div class="step-detail">
      <BusinessOperationPreview v-if="state === 'asking'" :preview="call.confirmation_preview" />
      <details class="tool-data" :open="state !== 'asking'">
        <summary>调用详情</summary>
        <dl>
          <dt>工具</dt><dd>{{ call.name }}</dd>
          <template v-if="call.input"><dt>参数</dt><dd><pre>{{ formattedInput }}</pre></dd></template>
          <template v-if="result"><dt>结果</dt><dd><pre :class="{ error: result.state === 'error' }">{{ formattedResult }}</pre></dd></template>
        </dl>
      </details>
      <p v-if="!result" class="step-note">{{ waitingLabel }}</p>
      <div v-if="state === 'asking' && canConfirm" class="agent-confirm">
        <span>请核对操作内容后确认</span>
        <button type="button" class="deny" :disabled="confirmationBusy" @click="confirm(false)">
          {{ pendingKey === `${replyId}:${call.id}:deny` ? '正在拒绝…' : '拒绝' }}
        </button>
        <button type="button" class="allow" :disabled="confirmationBusy" @click="confirm(true)">
          {{ pendingKey === `${replyId}:${call.id}:allow` ? '正在允许…' : '允许本次' }}
        </button>
      </div>
      <p v-else-if="state === 'asking'" class="step-note">等待请求发起人确认</p>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NIcon } from 'naive-ui'
import { ChevronRight, Loader, Tool } from '@vicons/tabler'
import BusinessOperationPreview from './BusinessOperationPreview.vue'
import type { AgentToolCallBlock, AgentToolResultBlock } from '@/types/agentRuntime'
import { agentToolLabel } from '@/utils/agentRuntimeLabels'
import { parseToolInput, toolPresentationState } from '@/utils/agentMessagePresentation'

const props = withDefaults(defineProps<{
  call: AgentToolCallBlock
  result?: AgentToolResultBlock
  replyId: string
  active: boolean
  interrupted?: boolean
  awaitingExternal?: boolean
  canConfirm?: boolean
  confirmationBusy?: boolean
  pendingKey?: string
}>(), { interrupted: false, awaitingExternal: false, canConfirm: true, confirmationBusy: false, pendingKey: '' })
const emit = defineEmits<{ confirm: [replyId: string, toolCall: AgentToolCallBlock, confirmed: boolean] }>()
const state = computed(() => props.awaitingExternal && props.active && !props.interrupted
  ? 'external' : toolPresentationState(props.call, props.result, props.active, props.interrupted))
const stateLabel = computed(() => ({
  asking: '等待确认', running: '执行中', success: '已完成', error: '失败',
  denied: '已拒绝', interrupted: '已停止', finished: '已结束',
  external: '等待结果',
})[state.value])
const description = computed(() => {
  const input = parseToolInput(props.call)
  const value = input.query || input.subject || input.file_path || input.path || input.title
  return typeof value === 'string' ? value : ''
})
const formattedInput = computed(() => {
  try { return JSON.stringify(JSON.parse(props.call.input), null, 2) } catch { return props.call.input }
})
const formattedResult = computed(() => {
  const output = props.result?.output
  if (typeof output === 'string') return output
  return output?.map(block => block.type === 'text' ? block.text : `[${block.source.media_type} 数据]`).join('\n') || ''
})
const waitingLabel = computed(() => ({
  asking: '该操作需要确认后才能执行。', running: '等待工具返回结果…',
  interrupted: '操作已停止。', finished: '本次调用已结束，未收到工具结果。',
  external: '等待操作结果…',
} as Record<string, string>)[state.value] || '')
function confirm(confirmed: boolean) {
  if (!props.canConfirm || props.confirmationBusy || state.value !== 'asking') return
  emit('confirm', props.replyId, props.call, confirmed)
}
</script>

<style scoped src="./AgentExecutionStep.css"></style>
<style scoped>
.tool-data { min-width: 0; color: #526a66; font-size: 12px; }
.tool-data > summary { cursor: pointer; padding: 3px 0; }
dl { display: grid; gap: 5px; margin: 8px 0 0; }
dt { color: #607873; font-weight: 600; }
dd { margin: 0 0 6px; overflow-wrap: anywhere; }
pre { margin: 0; padding: 8px; max-height: 240px; overflow: auto; border-radius: 5px; background: #f3f7f5;
  font: 12px/1.6 ui-monospace, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
pre.error { color: #a23f25; background: #fff5f1; }
.agent-confirm { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding-top: 6px; }
.agent-confirm > span { flex: 1 0 100%; font-size: 12px; color: #805822; }
button { padding: 6px 10px; border: 1px solid #c8d9d4; border-radius: 5px; font: inherit; font-size: 12px; cursor: pointer; }
.deny { color: #526a66; background: white; }.allow { color: white; background: #177b6d; border-color: #177b6d; }
button:disabled { opacity: .6; cursor: wait; }
button:focus-visible { outline: 2px solid #177b6d; outline-offset: 2px; }
</style>
