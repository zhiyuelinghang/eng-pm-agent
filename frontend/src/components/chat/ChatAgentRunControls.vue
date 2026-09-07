<template>
  <AgentMessageContent :runtime-trace="runtimeTrace" :content="isActive ? '' : item.content"
    :streaming="isActive" :can-confirm="canConfirm" :confirmation-busy="confirming" @confirm="confirm" />
  <button v-if="canStop" type="button" class="agent-run-stop" :disabled="stopping" @click="stop">
    {{ stopping ? '正在停止…' : '停止本次执行' }}
  </button>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { confirmProjectChatAgentTool, stopProjectChatAgentRun, type ProjectChatMessage } from '@/api/projectChat'
import AgentMessageContent from '@/components/agent/AgentMessageContent.vue'
import { runtimeTraceFromExtraData, type AgentToolCallBlock } from '@/types/agentRuntime'

const props = defineProps<{ item: ProjectChatMessage; currentUserId: number }>()
const emit = defineEmits<{ updated: [item: ProjectChatMessage] }>()
const notice = useMessage()
const stopping = ref(false)
const confirming = ref(false)
const isActive = computed(() => ['queued', 'creating', 'running', 'interrupting', 'awaiting_permission', 'awaiting_external_result']
  .includes(String(props.item.metadata?.runtime_status || '')))
const canStop = computed(() => props.item.sender_type === 'agent'
  && Number(props.item.metadata?.requester_user_id || 0) === props.currentUserId && isActive.value
  && props.item.metadata?.runtime_status !== 'interrupting')
const canConfirm = computed(() => canStop.value && props.item.metadata?.runtime_status === 'awaiting_permission')
const runtimeTrace = computed(() => runtimeTraceFromExtraData(props.item.metadata))

async function confirm(replyId: string, toolCall: AgentToolCallBlock, confirmed: boolean) {
  if (confirming.value || !canConfirm.value) return
  confirming.value = true
  try {
    emit('updated', await confirmProjectChatAgentTool(props.item.id, {
      reply_id: replyId, tool_call: toolCall, confirmed,
    }))
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '确认操作失败')
  } finally {
    confirming.value = false
  }
}

async function stop() {
  stopping.value = true
  try {
    emit('updated', await stopProjectChatAgentRun(props.item.id))
  } catch (error) {
    notice.error(error instanceof Error ? error.message : '停止执行失败')
  } finally {
    stopping.value = false
  }
}
</script>

<style scoped>
.agent-run-stop { margin: 6px 0; padding: 5px 10px; font-size: 12px; color: #475569;
  background: #fff; border: 1px solid #cbd5e1; border-radius: 6px; cursor: pointer; }
.agent-run-stop:disabled { cursor: wait; opacity: .6; }
</style>
