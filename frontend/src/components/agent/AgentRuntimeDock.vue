<template>
  <section v-if="hasContent" class="agent-runtime-dock" aria-label="当前智能体运行状态">
    <button
      v-if="collapsed"
      type="button"
      class="agent-runtime-dock-collapsed"
      aria-controls="agent-runtime-dock-content"
      aria-expanded="false"
      @click="collapsed = false"
    >
      <span class="agent-runtime-dock-dot" aria-hidden="true"></span>
      <strong>{{ collapsedTitle }}</strong>
      <span>{{ collapsedProgress }}</span>
      <em>{{ collapsedActivity }}</em>
      <small>{{ turnElapsed }}</small>
      <n-icon :size="16" aria-hidden="true"><ChevronUp /></n-icon>
    </button>

    <div v-else id="agent-runtime-dock-content" class="agent-runtime-dock-content">
      <header>
        <nav aria-label="运行状态视图">
          <button
            v-if="planTasks.length"
            type="button"
            :class="{ active: activeTab === 'plan' }"
            @click="activeTab = 'plan'"
          >
            <n-icon :size="15" aria-hidden="true"><ListCheck /></n-icon>
            执行计划
            <span>{{ planCompletedCount }}/{{ planTasks.length }}</span>
          </button>
          <button
            v-if="collaborationMembers.length"
            type="button"
            :class="{ active: activeTab === 'collaboration' }"
            @click="activeTab = 'collaboration'"
          >
            <n-icon :size="15" aria-hidden="true"><Users /></n-icon>
            协同进度
            <span>{{ collaborationCompletedCount }}/{{ collaborationMembers.length }}</span>
          </button>
        </nav>
        <div class="agent-runtime-dock-actions">
          <time>{{ turnElapsed }}</time>
          <button
            type="button"
            aria-controls="agent-runtime-dock-content"
            aria-expanded="true"
            @click="collapsed = true"
          >
            <n-icon :size="15" aria-hidden="true"><ChevronDown /></n-icon>
            收起
          </button>
        </div>
      </header>

      <div v-if="activeTab === 'plan' && planTasks.length" class="agent-runtime-plan">
        <div class="agent-runtime-progress" aria-hidden="true">
          <i :style="{ width: `${planProgress}%` }"></i>
        </div>
        <ul>
          <li v-for="task in planTasks" :key="String(task.id)" :class="task.state">
            <i aria-hidden="true"></i>
            <span>{{ task.subject }}</span>
            <small>
              <span v-if="task.owner">{{ task.owner }} · </span>{{ taskStateLabel(task.state) }}
            </small>
          </li>
        </ul>
      </div>

      <div v-else-if="collaborationMembers.length" class="agent-runtime-collaboration">
        <div class="agent-runtime-progress" aria-hidden="true">
          <i :style="{ width: `${collaborationProgress}%` }"></i>
        </div>
        <ul>
          <li v-for="member in collaborationMembers" :key="member.worker_session_id">
            <span class="agent-runtime-avatar">{{ member.worker_agent_name.slice(0, 1) }}</span>
            <span class="agent-runtime-member-main">
              <strong>{{ member.worker_agent_name }}</strong>
              <small>{{ collaborationActivityLabel(member) }}</small>
            </span>
            <span class="agent-runtime-member-state" :class="memberStatus(member)">
              <n-icon :size="14" aria-hidden="true">
                <Loader v-if="memberActive(member)" class="spin" />
                <AlertTriangle v-else-if="['failed', 'interrupted'].includes(memberStatus(member))" />
                <CircleCheck v-else />
              </n-icon>
              {{ memberStatusLabel(member) }}
            </span>
            <time>{{ memberElapsed(member) }}</time>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NIcon } from 'naive-ui'
import {
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  CircleCheck,
  ListCheck,
  Loader,
  Users,
} from '@vicons/tabler'
import type {
  AgentCollaborationMember,
  AgentRuntimeTrace,
  AgentTask,
} from '@/types/agentRuntime'
import { agentCollaborationActivityLabel } from '@/utils/agentRuntimeLabels'

type RuntimeDockTab = 'plan' | 'collaboration'

const props = defineProps<{
  runtimeTrace: AgentRuntimeTrace
}>()

const collapsed = ref(true)
const activeTab = ref<RuntimeDockTab>('plan')
const now = ref(Date.now())
let clock: ReturnType<typeof setInterval> | null = null
let previouslyHadCollaboration = false

const activeCollaborationStatuses = new Set([
  'idle',
  'queued',
  'running',
  'waiting',
])

const planTasks = computed(() => {
  const tasks = props.runtimeTrace.tasksContext?.tasks || []
  return tasks.some(task => ['pending', 'in_progress'].includes(task.state))
    ? tasks
    : []
})

const activeTeamIds = computed(() => new Set(
  props.runtimeTrace.collaborations
    .filter(member => memberActive(member))
    .map(member => member.team_id || '__default__'),
))

const collaborationMembers = computed(() => {
  if (!activeTeamIds.value.size) return []
  return props.runtimeTrace.collaborations.filter(member => (
    activeTeamIds.value.has(member.team_id || '__default__')
  ))
})

const hasContent = computed(() => (
  Boolean(planTasks.value.length || collaborationMembers.value.length)
))

const planCompletedCount = computed(() => planTasks.value.filter(
  task => ['completed', 'skipped'].includes(task.state),
).length)

const planProgress = computed(() => (
  planTasks.value.length
    ? Math.round(planCompletedCount.value * 100 / planTasks.value.length)
    : 0
))

const collaborationCompletedCount = computed(() => collaborationMembers.value.filter(
  member => ['reported', 'completed'].includes(memberStatus(member)),
).length)

const collaborationProgress = computed(() => (
  collaborationMembers.value.length
    ? Math.round(
        collaborationCompletedCount.value * 100 / collaborationMembers.value.length,
      )
    : 0
))

const collapsedTitle = computed(() => (
  collaborationMembers.value.length ? '协同进行中' : '执行计划'
))

const collapsedProgress = computed(() => {
  const parts: string[] = []
  if (planTasks.value.length) {
    parts.push(`计划 ${planCompletedCount.value}/${planTasks.value.length}`)
  }
  if (collaborationMembers.value.length) {
    parts.push(
      `协同 ${collaborationCompletedCount.value}/${collaborationMembers.value.length}`,
    )
  }
  return parts.join(' · ')
})

const collapsedActivity = computed(() => {
  if (collaborationMembers.value.length) {
    const active = collaborationMembers.value.find(member => memberActive(member))
    if (active) return `${active.worker_agent_name}：${collaborationActivityLabel(active)}`
  }
  return planTasks.value.find(task => task.state === 'in_progress')?.subject
    || planTasks.value.find(task => task.state === 'pending')?.subject
    || ''
})

const turnElapsed = computed(() => elapsedBetween(
  props.runtimeTrace.turnStartedAt,
  props.runtimeTrace.turnFinishedAt,
))

watch(
  [planTasks, collaborationMembers],
  () => {
    const hasCollaboration = collaborationMembers.value.length > 0
    if (hasCollaboration && !previouslyHadCollaboration) {
      activeTab.value = 'collaboration'
    } else if (activeTab.value === 'plan' && !planTasks.value.length) {
      activeTab.value = 'collaboration'
    } else if (
      activeTab.value === 'collaboration'
      && !collaborationMembers.value.length
    ) {
      activeTab.value = 'plan'
    }
    previouslyHadCollaboration = hasCollaboration
  },
  { immediate: true },
)

onMounted(() => {
  clock = setInterval(() => { now.value = Date.now() }, 1000)
})

onBeforeUnmount(() => {
  if (clock) clearInterval(clock)
})

function memberActive(member: AgentCollaborationMember) {
  return activeCollaborationStatuses.has(memberStatus(member))
}

function memberStatus(member: AgentCollaborationMember) {
  if (member.work_status === 'reported') return 'completed'
  if (
    ['idle', 'queued'].includes(member.work_status)
    && member.current_activity?.state === 'running'
  ) {
    return 'running'
  }
  return member.work_status
}

function memberStatusLabel(member: AgentCollaborationMember) {
  const labels: Record<string, string> = {
    idle: '等待启动',
    queued: '排队中',
    waiting: '等待中',
    running: '执行中',
    reported: '已反馈',
    completed: '已完成',
    failed: '失败',
    interrupted: '已中断',
  }
  const status = memberStatus(member)
  return labels[status] || status
}

function collaborationActivityLabel(member: AgentCollaborationMember) {
  const activity = member.current_activity
  if (!activity) {
    return memberActive(member) ? '正在建立协作会话' : memberStatusLabel(member)
  }
  return agentCollaborationActivityLabel(activity)
}

function memberElapsed(member: AgentCollaborationMember) {
  return elapsedBetween(
    member.started_at || member.assigned_at || null,
    member.settled_at || null,
  )
}

function elapsedBetween(startValue?: string | null, endValue?: string | null) {
  if (!startValue) return ''
  const start = Date.parse(startValue)
  const end = endValue ? Date.parse(endValue) : now.value
  if (!Number.isFinite(start) || !Number.isFinite(end)) return ''
  const seconds = Math.max(0, Math.round((end - start) / 1000))
  if (seconds < 60) return `${seconds}s`
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
}

function taskStateLabel(state: AgentTask['state']) {
  return ({
    pending: '待处理',
    in_progress: '进行中',
    completed: '已完成',
    skipped: '已跳过',
    failed: '执行失败',
  } as Record<string, string>)[state] || state
}
</script>

<style scoped>
.agent-runtime-dock { position:relative; z-index:2; min-width:0; border-top:1px solid #cfe0dc; background:#f7faf9; box-shadow:inset 3px 0 #218576; }
.agent-runtime-dock-collapsed { display:grid; width:100%; min-height:42px; grid-template-columns:auto auto auto minmax(0,1fr) auto auto; align-items:center; gap:9px; border:0; padding:0 14px 0 16px; color:#2d5b54; background:#f7faf9; font:inherit; text-align:left; cursor:pointer; transition:background .2s ease,color .2s ease; }
.agent-runtime-dock-collapsed:hover { color:#174f47; background:#eef6f3; }
.agent-runtime-dock-collapsed:active { transform:translateY(1px); }
.agent-runtime-dock-collapsed:focus-visible,.agent-runtime-dock-content button:focus-visible { outline:2px solid rgba(15,118,110,.28); outline-offset:-2px; }
.agent-runtime-dock-dot { width:7px; height:7px; border-radius:50%; background:#168b78; box-shadow:0 0 0 3px rgba(22,139,120,.12); animation:runtime-dock-pulse 1.6s ease-in-out infinite; }
.agent-runtime-dock-collapsed strong { font-size:12px; }
.agent-runtime-dock-collapsed > span:not(.agent-runtime-dock-dot) { color:#58746e; font-size:12px; font-variant-numeric:tabular-nums; white-space:nowrap; }
.agent-runtime-dock-collapsed em { min-width:0; overflow:hidden; color:#6d817c; font-size:12px; font-style:normal; text-overflow:ellipsis; white-space:nowrap; }
.agent-runtime-dock-collapsed small,.agent-runtime-dock-collapsed .n-icon { color:#70847f; font-size:12px; font-variant-numeric:tabular-nums; white-space:nowrap; }
.agent-runtime-dock-content { display:grid; max-height:min(30dvh,250px); grid-template-rows:auto minmax(0,1fr); }
.agent-runtime-dock-content > header { display:flex; min-width:0; align-items:center; justify-content:space-between; gap:12px; border-bottom:1px solid #dde8e5; padding:8px 12px 7px 15px; }
.agent-runtime-dock-content nav { display:flex; min-width:0; align-items:center; gap:5px; }
.agent-runtime-dock-content nav button { display:inline-flex; min-height:31px; align-items:center; gap:5px; border:0; border-radius:6px; padding:5px 8px; color:#68807b; background:transparent; font:inherit; font-size:12px; font-weight:750; cursor:pointer; transition:background .2s ease,color .2s ease; }
.agent-runtime-dock-content nav button:hover { color:#285b54; background:#edf4f2; }
.agent-runtime-dock-content nav button.active { color:#145f54; background:#e3f1ed; }
.agent-runtime-dock-content nav button span { color:#6c837e; font-size:12px; font-variant-numeric:tabular-nums; }
.agent-runtime-dock-actions { display:flex; flex:0 0 auto; align-items:center; gap:7px; }
.agent-runtime-dock-actions time { color:#748782; font-size:12px; font-variant-numeric:tabular-nums; }
.agent-runtime-dock-actions button { display:inline-flex; min-height:30px; align-items:center; gap:4px; border:0; border-radius:5px; padding:5px 7px; color:#657d78; background:transparent; font:inherit; font-size:12px; font-weight:700; cursor:pointer; }
.agent-runtime-dock-actions button:hover { color:#275c54; background:#e7f1ee; }
.agent-runtime-plan,.agent-runtime-collaboration { display:grid; min-height:0; grid-template-rows:auto minmax(0,1fr); gap:8px; padding:9px 13px 10px 16px; overflow:hidden; }
.agent-runtime-progress { height:4px; overflow:hidden; border-radius:999px; background:#dfeae7; }
.agent-runtime-progress i { display:block; height:100%; border-radius:inherit; background:#238b7b; transition:width .2s ease; }
.agent-runtime-plan ul,.agent-runtime-collaboration ul { display:grid; min-height:0; gap:4px; margin:0; padding:0; overflow-y:auto; list-style:none; }
.agent-runtime-plan li { display:grid; min-width:0; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:8px; border-radius:5px; padding:5px 7px; color:#5f7772; background:rgba(255,255,255,.7); font-size:12px; line-height:1.45; }
.agent-runtime-plan li > i { width:8px; height:8px; border:2px solid #9bb5af; border-radius:50%; }
.agent-runtime-plan li.in_progress > i { border-color:#238b7b; border-top-color:transparent; animation:runtime-dock-spin .8s linear infinite; }
.agent-runtime-plan li.completed > i,.agent-runtime-plan li.skipped > i { border-color:#4c8a68; background:#4c8a68; box-shadow:inset 0 0 0 2px #fff; }
.agent-runtime-plan li.failed > i { border-color:#c85829; background:#c85829; box-shadow:inset 0 0 0 2px #fff; }
.agent-runtime-plan li > span { min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.agent-runtime-plan li > small { color:#81928e; font-size:12px; white-space:nowrap; }
.agent-runtime-plan li.completed > span,.agent-runtime-plan li.skipped > span { color:#83948f; text-decoration:line-through; }
.agent-runtime-collaboration li { display:grid; min-width:0; grid-template-columns:28px minmax(0,1fr) auto 52px; align-items:center; gap:8px; border-radius:5px; padding:6px 7px; background:rgba(255,255,255,.72); }
.agent-runtime-avatar { display:grid; width:28px; height:28px; place-items:center; border-radius:7px; color:#176d62; background:#e5f2ef; font-size:12px; font-weight:800; }
.agent-runtime-member-main { display:grid; min-width:0; gap:1px; }
.agent-runtime-member-main strong,.agent-runtime-member-main small { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.agent-runtime-member-main strong { color:#294e48; font-size:12px; }
.agent-runtime-member-main small { color:#788d88; font-size:12px; }
.agent-runtime-member-state { display:flex; align-items:center; gap:4px; color:#55736d; font-size:12px; white-space:nowrap; }
.agent-runtime-member-state.running,.agent-runtime-member-state.queued,.agent-runtime-member-state.idle,.agent-runtime-member-state.waiting { color:#0c7b69; }
.agent-runtime-member-state.failed,.agent-runtime-member-state.interrupted { color:#a44a31; }
.agent-runtime-collaboration li > time { color:#879792; font-size:12px; font-variant-numeric:tabular-nums; text-align:right; white-space:nowrap; }
.spin { animation:runtime-dock-spin .8s linear infinite; }
@keyframes runtime-dock-spin { to { transform:rotate(360deg); } }
@keyframes runtime-dock-pulse { 50% { opacity:.52; transform:scale(.86); } }
@media (max-width:700px) {
  .agent-runtime-dock-collapsed { grid-template-columns:auto auto minmax(0,1fr) auto; }
  .agent-runtime-dock-collapsed > span:not(.agent-runtime-dock-dot),.agent-runtime-dock-collapsed small { display:none; }
  .agent-runtime-dock-content > header { align-items:flex-start; }
  .agent-runtime-dock-actions time { display:none; }
  .agent-runtime-collaboration li { grid-template-columns:28px minmax(0,1fr) auto; }
  .agent-runtime-collaboration li > time { display:none; }
}
</style>
