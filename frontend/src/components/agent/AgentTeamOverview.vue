<template>
  <section v-if="teams.length" class="agent-team-overviews" aria-label="团队协同概览">
    <details v-for="team in teams" :key="team.id" class="agent-team-overview"
      :open="expanded[team.id] || false" @toggle="onToggle(team.id, $event)">
      <summary>
        <n-icon :size="16" aria-hidden="true"><Users /></n-icon>
        <strong>{{ team.name }} · 已完成 {{ team.completedCount }}/{{ team.members.length }}</strong>
        <span class="team-toggle">{{ expanded[team.id] ? '收起' : '展开' }}</span>
        <n-icon class="team-chevron" :size="15" aria-hidden="true"><ChevronRight /></n-icon>
      </summary>
      <ul aria-label="团队成员当前进度">
        <li v-for="member in team.members" :key="member.id" :data-worker-id="member.id">
          <n-icon :size="15" class="member-icon" :class="{ failed: member.failed }" aria-hidden="true">
            <CircleCheck v-if="member.completed" />
            <Loader v-else-if="member.running" class="spin" />
            <AlertTriangle v-else-if="member.failed" />
            <Circle v-else />
          </n-icon>
          <span class="member-main">
            <strong>{{ member.name }}</strong>
            <small v-if="member.activity">{{ member.activity }}</small>
          </span>
          <span class="member-state" :class="{ failed: member.failed }">{{ member.stateLabel }}</span>
        </li>
      </ul>
    </details>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NIcon } from 'naive-ui'
import { AlertTriangle, ChevronRight, Circle, CircleCheck, Loader, Users } from '@vicons/tabler'
import type { AgentRuntimeTrace } from '@/types/agentRuntime'
import { agentTeamOverviewPresentation } from '@/utils/agentTeamOverviewPresentation'

const props = defineProps<{ runtimeTrace?: AgentRuntimeTrace | null }>()
const teams = computed(() => agentTeamOverviewPresentation(props.runtimeTrace))
const expanded = ref<Record<string, boolean>>({})
function onToggle(id: string, event: Event) { expanded.value[id] = (event.target as HTMLDetailsElement).open }
</script>

<style scoped>
.agent-team-overviews { display:grid; gap:8px; min-width:0; }
.agent-team-overview { min-width:0; border:1px solid #dce5e0; border-radius:8px; background:#f8faf9; color:#3b5e50; font-size:13px; line-height:1.6; }
summary { display:flex; align-items:center; gap:8px; padding:9px 12px; cursor:pointer; list-style:none; }
summary::-webkit-details-marker { display:none; }summary:focus-visible { outline:2px solid #4a8870; outline-offset:2px; border-radius:6px; }
summary strong { min-width:0; font-size:13px; font-weight:650; overflow-wrap:anywhere; }.team-toggle { margin-left:auto; color:#6a8176; font-size:12px; white-space:nowrap; }
.team-chevron { flex-shrink:0; transition:transform .15s ease; }details[open] .team-chevron { transform:rotate(90deg); }
ul { display:grid; gap:4px; margin:0; padding:0 12px 10px; list-style:none; }
li { display:grid; grid-template-columns:16px minmax(0,1fr) auto; align-items:start; gap:8px; padding:5px 0; }
.member-icon { margin-top:3px; }.member-main { display:grid; min-width:0; gap:1px; overflow-wrap:anywhere; }
.member-main strong { font-size:13px; font-weight:550; }.member-main small { color:#748278; font-size:12px; }
.member-state { color:#6a8176; font-size:12px; white-space:nowrap; }.failed { color:#a34d36; }
.spin { animation:team-overview-spin 1s linear infinite; }@keyframes team-overview-spin { to { transform:rotate(360deg); } }
@media (prefers-reduced-motion:reduce) { .spin { animation:none; }.team-chevron { transition:none; } }
</style>
