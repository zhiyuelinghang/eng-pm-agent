<template>
  <section v-if="state === 'asking'" class="agent-business-confirmation" aria-label="待确认的业务操作">
    <header><n-icon :size="16"><ShieldCheck /></n-icon><strong>{{ canConfirm ? '需要你的确认' : '等待请求发起人确认' }}</strong></header>
    <BusinessOperationPreview v-if="hasPreview" :preview="call.confirmation_preview" />
    <p v-else>暂时无法展示这项操作的具体影响，不能确认执行。你可以拒绝本次操作后让 Dobby 重新说明。</p>
    <div v-if="canConfirm" class="agent-confirm">
      <button type="button" class="deny" :disabled="confirmationBusy" @click="confirm(false)">
        {{ pendingKey === `${replyId}:${call.id}:deny` ? '正在拒绝…' : '拒绝' }}
      </button>
      <button type="button" class="allow" :disabled="confirmationBusy || !hasPreview" @click="confirm(true)">
        {{ pendingKey === `${replyId}:${call.id}:allow` ? '正在确认…' : '确认本次操作' }}
      </button>
    </div>
    <p v-else>等待请求发起人确认。</p>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NIcon } from 'naive-ui'
import { ShieldCheck } from '@vicons/tabler'
import BusinessOperationPreview from './BusinessOperationPreview.vue'
import type { AgentToolCallBlock, AgentToolResultBlock } from '@/types/agentRuntime'
import { toolPresentationState } from '@/utils/agentMessagePresentation'

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
const hasPreview = computed(() => Boolean(props.call.confirmation_preview?.operation_label
  && props.call.confirmation_preview?.target_name && props.call.confirmation_preview?.impact))
function confirm(confirmed: boolean) {
  if (!props.canConfirm || props.confirmationBusy || state.value !== 'asking' || (confirmed && !hasPreview.value)) return
  emit('confirm', props.replyId, props.call, confirmed)
}
</script>

<style scoped>
.agent-business-confirmation { min-width: 0; padding: 14px; border: 1px solid #d6e5df; border-radius: 9px; background: #fbfdfb; }
header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; color: #31594e; font-size: 13px; }
p { margin: 10px 0; color: #607873; font-size: 13px; line-height: 1.7; }
.agent-confirm { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 8px; padding-top: 12px; }
button { padding: 7px 12px; border: 1px solid #c8d9d4; border-radius: 6px; font: inherit; font-size: 13px; cursor: pointer; }
.deny { color: #526a66; background: white; }.allow { color: white; background: #177b6d; border-color: #177b6d; }
button:disabled { opacity: .6; cursor: not-allowed; }
button:focus-visible { outline: 2px solid #177b6d; outline-offset: 2px; }
</style>
