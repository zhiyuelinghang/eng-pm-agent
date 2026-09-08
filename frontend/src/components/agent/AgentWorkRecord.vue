<template>
  <div class="agent-work-record" :class="`state-${state}`">
    <n-icon :size="16"><Loader v-if="running" class="spin" /><CircleCheck v-else-if="state === 'success' || state === 'completed'" /><Activity v-else /></n-icon>
    <span class="work-label">{{ label }}</span>
    <span class="work-state">{{ statusLabel }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NIcon } from 'naive-ui'
import { Activity, CircleCheck, Loader } from '@vicons/tabler'
const props = defineProps<{ label: string; state: string }>()
const running = computed(() => ['running', 'queued', 'idle'].includes(props.state))
const statusLabel = computed(() => ({
  running: '处理中', queued: '等待处理', idle: '等待处理', asking: '等待确认',
  external: '等待结果', waiting: '等待反馈', success: '已完成', completed: '已完成',
  reported: '已反馈', error: '处理失败', failed: '处理失败', denied: '已拒绝',
  interrupted: '已停止', finished: '已结束',
} as Record<string, string>)[props.state] || '已结束')
</script>

<style scoped>
.agent-work-record { display:flex; align-items:center; gap:9px; min-width:0; padding:9px 10px; border-radius:6px; background:#edf4f1; color:#52746a; font-size:13px; line-height:1.6; }
.work-label { flex:1; min-width:0; overflow-wrap:anywhere; }.work-state { flex-shrink:0; font-size:12px; }
.state-error,.state-failed,.state-denied { color:#a4472d; }.spin { animation:spin .8s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }@media (prefers-reduced-motion:reduce) { .spin { animation:none; } }
</style>
