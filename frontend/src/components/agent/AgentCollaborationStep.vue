<template>
  <details class="agent-execution-step agent-collaboration-step" :open="hasPendingWork">
    <summary>
      <n-icon :size="16"><Users /></n-icon>
      <span class="step-title"><strong>{{ step.name }}</strong><small v-if="step.task">{{ step.task }}</small></span>
      <span class="step-state" :class="`state-${status}`">
        <n-icon v-if="active && ['queued', 'idle', 'running'].includes(status)" :size="13"><Loader class="spin" /></n-icon>
        {{ statusLabel }}
      </span>
      <n-icon class="step-chevron" :size="14"><ChevronRight /></n-icon>
    </summary>
    <div class="step-detail">
      <p v-if="step.task" class="step-note">{{ step.task }}</p>
      <ol v-if="step.activities.length" aria-label="协同工作记录">
        <li v-for="(activity, index) in step.activities" :key="`${activity.reply_id}:${activity.tool_call_id}:${index}`">
          <n-icon :size="14"><Tool /></n-icon><span>{{ agentCollaborationActivityLabel(activity) }}</span>
        </li>
      </ol>
      <AgentToolCall v-if="step.call && needsCallDetails" :call="step.call" :result="step.result"
        :reply-id="step.replyId || ''" :active="active" :interrupted="interrupted"
        :can-confirm="canConfirm" :confirmation-busy="confirmationBusy" :pending-key="pendingKey"
        @confirm="forwardConfirmation" />
      <template v-for="entry in step.pending" :key="`${entry.worker_session_id}:${entry.reply_id}`">
        <AgentToolCall v-for="call in entry.event.tool_calls || []" :key="call.id" :call="call"
          :reply-id="entry.reply_id" :active="active" :interrupted="interrupted"
          :awaiting-external="entry.event_type === 'require_external_execution'"
          :can-confirm="canConfirm && entry.event_type === 'require_user_confirm'"
          :confirmation-busy="confirmationBusy" :pending-key="pendingKey" @confirm="forwardConfirmation" />
      </template>
      <p v-if="!step.task && !step.activities.length && !step.pending.length && !needsCallDetails" class="step-note">
        {{ active ? '正在处理请求…' : statusLabel }}
      </p>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NIcon } from 'naive-ui'
import { ChevronRight, Loader, Tool, Users } from '@vicons/tabler'
import AgentToolCall from './AgentToolCall.vue'
import type { AgentToolCallBlock } from '@/types/agentRuntime'
import type { CollaborationStep } from '@/utils/agentMessagePresentation'
import { agentCollaborationActivityLabel } from '@/utils/agentRuntimeLabels'

const props = withDefaults(defineProps<{
  step: CollaborationStep
  active: boolean
  interrupted?: boolean
  canConfirm?: boolean
  confirmationBusy?: boolean
  pendingKey?: string
}>(), { interrupted: false, canConfirm: true, confirmationBusy: false, pendingKey: '' })
const emit = defineEmits<{ confirm: [replyId: string, toolCall: AgentToolCallBlock, confirmed: boolean] }>()
const hasPendingWork = computed(() => props.active && (props.step.status === 'asking' || props.step.pending.length > 0))
const needsConfirmation = computed(() => props.active && (props.step.status === 'asking'
  || props.step.pending.some(entry => entry.event_type === 'require_user_confirm')))
const needsCallDetails = computed(() => props.step.status === 'asking'
  || ['error', 'denied', 'interrupted'].includes(props.step.result?.state || ''))
const status = computed(() => needsConfirmation.value ? 'asking' : hasPendingWork.value ? 'waiting' : props.step.status)
const statusLabel = computed(() => ({
  queued: '等待处理', idle: '等待处理', running: '处理中', waiting: '等待反馈', asking: '等待确认',
  reported: '已反馈', completed: '已完成', failed: '失败', error: '失败', denied: '已拒绝',
  interrupted: '已停止', finished: '已结束',
} as Record<string, string>)[status.value] || '处理中')
function forwardConfirmation(replyId: string, call: AgentToolCallBlock, confirmed: boolean) {
  emit('confirm', replyId, call, confirmed)
}
</script>

<style scoped src="./AgentExecutionStep.css"></style>
<style scoped>
ol { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; }
li { display: flex; align-items: center; gap: 7px; font-size: 12px; line-height: 1.5; }
li span { overflow-wrap: anywhere; }
</style>
