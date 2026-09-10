<template>
  <details v-if="plan.tasks.length" class="agent-task-plan" :open="expanded" @toggle="onToggle">
    <summary>
      <n-icon :size="16" aria-hidden="true"><ListCheck /></n-icon>
      <strong>执行计划</strong>
      <span class="plan-count">{{ plan.completedCount }} / {{ plan.tasks.length }}</span>
      <span class="plan-toggle">{{ expanded ? '收起' : '展开' }}</span>
      <n-icon class="plan-chevron" :size="15" aria-hidden="true"><ChevronRight /></n-icon>
    </summary>
    <div class="plan-body">
      <div class="plan-progress" role="progressbar" aria-label="执行计划完成进度"
        :aria-valuenow="plan.completedCount" :aria-valuemin="0" :aria-valuemax="plan.tasks.length">
        <i :style="{ width: `${plan.progress}%` }"></i>
      </div>
      <ul>
        <li v-for="task in plan.tasks" :key="task.id" :data-task-id="task.id" :class="`task-${task.state}`">
          <n-icon :size="15" class="task-icon" aria-hidden="true">
            <CircleCheck v-if="['completed', 'skipped'].includes(task.state)" />
            <Loader v-else-if="task.state === 'in_progress' && runtimeTrace?.status === 'running'" class="spin" />
            <AlertTriangle v-else-if="task.state === 'failed'" />
            <Circle v-else />
          </n-icon>
          <div class="task-main">
            <span class="task-subject">{{ task.subject }}</span>
            <span v-if="task.owner" class="task-owner">负责人：{{ task.owner }}</span>
            <span v-if="task.blockers.length" class="task-blockers">等待：{{ task.blockers.join('、') }}</span>
          </div>
          <span class="task-state">{{ task.stateLabel }}</span>
        </li>
      </ul>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NIcon } from 'naive-ui'
import { AlertTriangle, ChevronRight, Circle, CircleCheck, ListCheck, Loader } from '@vicons/tabler'
import type { AgentRuntimeTrace } from '@/types/agentRuntime'
import { agentTaskPlanPresentation } from '@/utils/agentTaskPlanPresentation'

const props = defineProps<{ runtimeTrace?: AgentRuntimeTrace | null }>()
const plan = computed(() => agentTaskPlanPresentation(props.runtimeTrace))
const expanded = ref(true)
function onToggle(event: Event) { expanded.value = (event.target as HTMLDetailsElement).open }
</script>

<style scoped>
.agent-task-plan { min-width:0; border:1px solid #d5e5dd; border-radius:8px; background:#f7faf8; color:#355e50; font-size:13px; line-height:1.6; }
summary { display:flex; align-items:center; gap:8px; padding:10px 12px; cursor:pointer; list-style:none; }
summary::-webkit-details-marker { display:none; }
summary:focus-visible { outline:2px solid #4a8870; outline-offset:2px; border-radius:6px; }
summary strong { font-size:13px; font-weight:650; }.plan-count { color:#547365; font-size:12px; font-variant-numeric:tabular-nums; }
.plan-toggle { margin-left:auto; color:#6a8176; font-size:12px; }.plan-chevron { transition:transform .15s ease; }
details[open] .plan-chevron { transform:rotate(90deg); }.plan-body { padding:0 12px 11px; }
.plan-progress { height:4px; margin-bottom:8px; overflow:hidden; border-radius:4px; background:#e2ece6; }
.plan-progress i { display:block; height:100%; border-radius:inherit; background:#3a8b67; transition:width .2s ease; }
ul { display:grid; gap:3px; margin:0; padding:0; list-style:none; }
li { display:grid; grid-template-columns:16px minmax(0,1fr) auto; align-items:start; gap:8px; padding:6px 0; }
.task-icon { margin-top:3px; }.task-main { display:grid; min-width:0; gap:1px; }.task-subject { overflow-wrap:anywhere; }
.task-owner,.task-blockers { color:#738278; font-size:12px; overflow-wrap:anywhere; }.task-state { padding-top:1px; color:#6a8176; font-size:12px; white-space:nowrap; }
.task-completed,.task-skipped { color:#74867b; }.task-in_progress .task-state { color:#25744f; }.task-failed,.task-failed .task-state { color:#a34d36; }
.spin { animation:task-plan-spin 1s linear infinite; }@keyframes task-plan-spin { to { transform:rotate(360deg); } }
@media (prefers-reduced-motion:reduce) { .spin { animation:none; }.plan-chevron,.plan-progress i { transition:none; } }
</style>
