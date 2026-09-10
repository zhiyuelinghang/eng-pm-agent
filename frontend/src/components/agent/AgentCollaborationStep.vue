<template>
  <details class="agent-collaboration-step" :open="isOpen">
    <summary @click.prevent="openOverride = !isOpen">
      <span class="member-avatar" aria-hidden="true">{{ step.name.slice(0, 1) }}</span>
      <span class="member-heading">
        <span class="member-identity"><strong>{{ step.name }}</strong><span v-if="step.teamName" class="member-team">{{ step.teamName }}</span></span>
        <span class="member-task">{{ shortTask || invitationLabel }}</span>
      </span>
      <span class="member-progress">
        <span class="member-state" :class="`state-${state}`"><n-icon v-if="spinning" :size="13"><Loader class="spin" /></n-icon>{{ stateLabel }}</span>
        <span v-if="elapsed" class="member-elapsed">{{ elapsed }}</span>
      </span>
      <n-icon class="member-chevron" :size="15"><ChevronRight /></n-icon>
    </summary>
    <div class="member-detail">
      <details v-if="task && task.length > 70" class="member-task-detail">
        <summary>分配任务</summary><p>{{ task }}</p>
      </details>
      <p v-else-if="task" class="member-note">{{ task }}</p>
      <div class="member-meta"><span>{{ invitationLabel }}</span><span v-if="step.assignedAt">分配于 <time :datetime="step.assignedAt">{{ collaborationTime(step.assignedAt) }}</time></span></div>
      <ol v-if="step.activities.length" class="member-activities" :aria-label="`${step.name}的工作记录`">
        <li v-for="(activity, index) in step.activities" :key="`${activity.reply_id}:${activity.tool_call_id}:${index}`">
          <time :datetime="activity.created_at">{{ collaborationTime(activity.created_at) }}</time>
          <AgentWorkRecord :label="collaborationActivityLabel(activity)" :state="collaborationActivityState(activity, state)" />
        </li>
      </ol>
      <p v-else class="member-note">{{ isWorking ? '工作记录将在处理过程中更新。' : '本次没有更多工作记录。' }}</p>
      <p v-if="state === 'asking'" class="member-note">等待确认后继续，具体变更见下方确认区。</p>
      <p v-else-if="state === 'external'" class="member-note">已提交处理请求，正在等待结果返回。</p>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NIcon } from 'naive-ui'
import { ChevronRight, Loader } from '@vicons/tabler'
import AgentWorkRecord from './AgentWorkRecord.vue'
import type { CollaborationStep } from '@/utils/agentMessagePresentation'
import { collaborationActivityLabel, collaborationActivityState, collaborationElapsed, collaborationIsOpen,
  collaborationIsWorking, collaborationState, collaborationStateLabel, collaborationTask,
  collaborationTime } from '@/utils/agentCollaborationPresentation'

const props = withDefaults(defineProps<{ step: CollaborationStep; active: boolean; interrupted?: boolean }>(), { interrupted: false })
const openOverride = ref<boolean | null>(null)
watch(() => props.step.key, () => { openOverride.value = null })
const state = computed(() => collaborationState(props.step, props.active, props.interrupted))
const stateLabel = computed(() => collaborationStateLabel(state.value))
const isWorking = computed(() => collaborationIsWorking(state.value))
const isOpen = computed(() => collaborationIsOpen(state.value, openOverride.value))
const spinning = computed(() => props.active && ['running', 'queued', 'idle'].includes(state.value))
const task = computed(() => collaborationTask(props.step.task))
const shortTask = computed(() => collaborationTask(props.step.task, 70))
const invitationLabel = computed(() => props.step.call?.presentation?.label?.trim() || '协同处理任务')
const now = ref(Date.now())
const elapsed = computed(() => collaborationElapsed(props.step, state.value, now.value))
let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => { timer = setInterval(() => { if (props.active && isWorking.value) now.value = Date.now() }, 1000) })
onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<style scoped src="./AgentCollaborationStep.css"></style>
