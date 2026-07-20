<template>
  <header class="app-header">
    <div class="header-left">
      <span class="section-badge">工程管理平台</span>
      <span class="page-title">{{ pageTitle }}</span>
    </div>

    <div class="header-right">
      <label class="global-search">
        <n-icon :size="15"><Search /></n-icon>
        <input type="search" placeholder="搜索任务、资料、风险源" />
      </label>
      <button class="header-icon-btn" title="通知中心">
        <n-icon :size="16"><Bell /></n-icon>
        <span v-if="noticeCount > 0">{{ noticeCount }}</span>
      </button>
      <n-dropdown
        :options="projectOptions"
        :theme-overrides="dropdownTheme"
        :menu-props="projectMenuProps"
        @select="handleProjectChange"
        trigger="click"
      >
        <button class="project-switcher">
          <div class="proj-status-dot"></div>
          <div class="proj-info">
            <span class="proj-name">{{ currentProject?.name ?? '未选项目' }}</span>
            <span class="proj-meta">{{ currentProject?.ownerUnit ?? '—' }}</span>
          </div>
          <n-icon :size="13" style="color:var(--text-muted);flex-shrink:0"><ChevronDown /></n-icon>
        </button>
      </n-dropdown>
    </div>
  </header>
</template>

<script setup lang="ts">
import { computed, h } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { NDropdown, NIcon } from 'naive-ui'
import { Bell, ChevronDown, Check, Search } from '@vicons/tabler'

const route = useRoute()
const store = useAppStore()
const currentProject = computed(() => store.projects.find((p: any) => p.id === store.currentProjectId))
const noticeCount = computed(() => store.overdueTasks.length + store.waitingConfirmTasks.length + store.pendingDrafts.length)

const titleMap: Record<string, string> = {
  '/workbench': '工作首页',
  '/ai':        '智能协同',
  '/tasks':     '任务管理',
  '/project':   '项目状态',
  '/docs':      '工程资料',
  '/settings':  '工程配置',
}
const pageTitle = computed(() => {
  for (const [prefix, title] of Object.entries(titleMap)) {
    if (route.path.startsWith(prefix)) return title
  }
  return ''
})

const projectOptions = computed(() =>
  store.projects.flatMap((p: any, index: number) => [
    ...(index > 0 ? [{ type: 'divider' as const, key: `project-divider-${p.id}` }] : []),
    {
      label: () => h('div', { style: 'display:flex;align-items:center;gap:10px;min-width:190px;padding:3px 0' }, [
        h('div', { style: 'width:6px;height:6px;border-radius:50%;background:#047857;flex-shrink:0;margin-top:2px' }),
        h('div', { style: 'flex:1;min-width:0' }, [
          h('div', { style: 'font-size:13px;font-weight:500;color:#1B2430;line-height:1.4' }, p.name),
          h('div', { style: 'font-size:11px;color:#8792A2;line-height:1.4' }, p.ownerUnit),
        ]),
        p.id === store.currentProjectId
          ? h(NIcon, { size: 14, color: '#E8590C' }, { default: () => h(Check) })
          : h('div', { style: 'width:14px' }),
      ]),
      key: p.id,
    },
  ])
)

const handleProjectChange = (id: string) => { void store.selectProject(id) }
const projectMenuProps = () => ({ class: 'project-switcher-dropdown' })

const dropdownTheme = {
  borderRadius: '8px',
  boxShadow: '0 8px 24px rgba(23,32,46,0.14), 0 0 0 1px rgba(23,32,46,0.05)',
}
</script>

<style scoped>
.app-header {
  height: var(--header-height);
  background: rgba(255,255,255,0.92);
  border-bottom: 1px solid rgba(27,36,48,0.08);
  backdrop-filter: blur(18px);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  flex-shrink: 0;
  gap: 12px;
}
.header-left { display: flex; align-items: center; gap: 10px; min-width: 0; }
.section-badge {
  flex-shrink: 0;
  padding: 4px 8px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 750;
  background: #edf5f1;
  color: #0f766e;
}
.page-title { font-size: 15px; font-weight: 750; color: var(--text-primary); }

.header-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.global-search {
  width: min(30vw, 320px);
  height: 34px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  border: 1px solid var(--border-emphasis);
  border-radius: 6px;
  color: var(--text-muted);
  background: #fff;
}
.global-search input {
  min-width: 0;
  flex: 1;
  border: 0;
  outline: 0;
  font: inherit;
  color: var(--text-primary);
  background: transparent;
}
.header-icon-btn {
  width: 34px;
  height: 34px;
  border: 1px solid var(--border-emphasis);
  border-radius: var(--radius-sm);
  background: transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
  transition: var(--transition);
  position: relative;
}
.header-icon-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.header-icon-btn span {
  position: absolute;
  top: -5px;
  right: -5px;
  min-width: 17px;
  height: 17px;
  display: grid;
  place-items: center;
  padding: 0 4px;
  border-radius: 5px;
  background: var(--color-primary);
  color: #fff;
  font-size: 10px;
  font-weight: 800;
}
.project-switcher {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px 6px 10px;
  background: var(--bg-card);
  border: 1px solid var(--border-emphasis);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: var(--transition);
  min-width: 160px;
  max-width: none;
}
.project-switcher:hover { border-color: var(--color-primary); background: var(--bg-elevated); }
.proj-status-dot {
  width: 7px; height: 7px;
  background: var(--color-success);
  border-radius: 50%;
  flex-shrink: 0;
}
.proj-info { display: flex; flex-direction: column; align-items: flex-start; flex: 1; min-width: 0; }
.proj-name { font-size: 12px; font-weight: 600; color: var(--text-primary); white-space: nowrap; }
.proj-meta { font-size: 11px; color: var(--text-muted); }

:global(.project-switcher-dropdown .n-dropdown-divider) {
  margin: 9px 0;
}

@media (max-width: 860px) {
  .global-search { display: none; }
  .project-switcher { min-width: 0; max-width: 180px; }
  .proj-meta { display: none; }
}
</style>

